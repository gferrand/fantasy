"""DM-only Discord gateway for on-demand fantasy advisor tasks."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

import discord
from discord import app_commands

from .advisor_router import AdvisorRoute, RoutingError
from .automation import (
    AppConfig,
    AutomationError,
    EXPECTED_MANAGER_ID,
    build_report_header,
    claim_discord_message,
    load_local_player_catalog,
    load_advisor_context,
    persist_discord_channel_id,
    persist_discord_ready_state,
    persist_advisor_context_event,
    load_registry,
    run_gameweek_web_briefing,
    run_injury_web_briefing,
    run_rotation_web_briefing,
    run_trade_web_briefing,
    run_watchlist_web_briefing,
    run_scheduled_task,
    split_discord_message,
    update_player_catalog,
    watchlist_file,
)
from .attachment_intake import (
    AttachmentIntakeError,
    normalize_attachment_async,
    classify_attachment,
    validate_attachment_size,
)
from .context_store import DISCORD_ASSISTANT_RESPONSE, DISCORD_USER_MESSAGE
from .interactive_advisor import (
    RequestDeadline,
    current_evidence_envelope,
    finalize_advisor_from_evidence,
    run_advisor,
)
from .sleeper import SleeperDataError
from .discord_presentation import (
    advisor_header,
    error_card,
    help_menu,
    private_advisor_only,
    response_limit_notice,
    task_menu,
    player_catalog_updated,
    waiver_header,
    watchlist_card,
    watchlist_change,
    watchlist_empty,
    watchlist_stats_card,
    working_card,
    no_viable_trade_package,
    guardian_acknowledged,
    guardian_status,
)
from .deadline_guardian import acknowledge_active_events, active_events, parse_guardian_intent
from .watchlist import (
    WatchlistError,
    WatchlistResolutionError,
    add_watchlist_player,
    list_watchlist,
    remove_watchlist_player,
    parse_watchlist_intent,
    resolve_saved_watchlist_player,
    resolve_watchlist_player,
)
from .intelligence_capabilities import (
    get_gameweek_prepare_context,
    get_gameweek_recap_context,
    get_injury_opportunity_context,
    get_rotation_context,
    get_trade_context,
    get_watchlist_stats,
)
from .lineup_alerts import load_fixture_schedule, load_persisted_fixture_schedule
from .injury_opportunities import injury_timeline_research_context, render_injury_opportunities
from .watchlist_recommendations import (
    load_current_watchlist_recommendation_context,
    watchlist_outlook_context,
    watchlist_recommendation_context,
)


LOGGER = logging.getLogger(__name__)
WAIVER_ANALYSIS_REQUEST = (
    "Provide the complete on-demand waiver analysis for Los Blancos using the "
    "supplied live shortlist and roster-aware swap signals."
)


def build_client(config: AppConfig) -> discord.Client:
    """Build a private-DM client plus user-install slash commands.

    Discord user-installed apps are command-oriented.  The slash commands are
    therefore the durable entry point for this no-server installation, while
    ``on_message`` remains available when Discord delivers ordinary bot-DM
    messages (for example after a bot DM is opened explicitly).
    """

    intents = discord.Intents.none()
    # Keep guild metadata only so `message.guild is not None` is a reliable
    # DM boundary. No guild message is ever processed or answered.
    intents.guilds = True
    intents.messages = True
    intents.message_content = True
    client = discord.Client(intents=intents)
    command_tree = app_commands.CommandTree(client)
    # Expose the tree for local registration checks without changing Discord's
    # command-routing behavior.
    client._fantasy_command_tree = command_tree  # type: ignore[attr-defined]
    run_lock = asyncio.Lock()
    command_sync_complete = False

    async def send_chunks(channel: discord.abc.Messageable, text: str) -> None:
        allowed_mentions = discord.AllowedMentions.none()
        for chunk in split_discord_message(text):
            await channel.send(chunk, allowed_mentions=allowed_mentions)

    async def set_online_presence() -> None:
        """Report a healthy local worker without affecting DM-only behavior."""
        try:
            await asyncio.wait_for(
                client.change_presence(status=discord.Status.online),
                timeout=5,
            )
            LOGGER.info("Fantasy Discord presence set online")
        except Exception:
            # Presence is best-effort. A Discord gateway that can serve DMs
            # must remain ready if this optional update is unavailable.
            LOGGER.warning("Fantasy Discord presence update failed", exc_info=True)

    def schedule_online_presence() -> None:
        asyncio.create_task(set_online_presence())

    def compact_interaction_error(prefix: str, exc: Exception) -> str:
        """Keep an interaction error inside Discord's 2,000-character limit."""

        text = error_card(prefix, str(exc))
        if len(text) <= 1900:
            return text
        return text[:1850].rstrip() + "\n*Details truncated.*"

    async def edit_interaction_with_chunks(interaction: discord.Interaction, text: str) -> None:
        """Complete an interaction without silently truncating a long watchlist report."""

        chunks = split_discord_message(text, limit=1900)
        if len(chunks) > 5:
            chunks = chunks[:4] + [response_limit_notice()]
        await interaction.edit_original_response(
            content=chunks[0],
            allowed_mentions=discord.AllowedMentions.none(),
        )
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, allowed_mentions=discord.AllowedMentions.none())

    async def edit_injury_interaction(interaction: discord.Interaction, text: str) -> None:
        """Deliver the complete injury report as DM messages without attachments."""

        chunks = split_discord_message(text, limit=1900)
        await interaction.edit_original_response(
            content=chunks[0],
            allowed_mentions=discord.AllowedMentions.none(),
        )
        # User-installed interactions have a small follow-up webhook budget.
        # This command is DM-only, so send the remaining chunks through the DM
        # channel to preserve the complete inventory without an attachment.
        for chunk in chunks[1:]:
            await interaction.channel.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def bounded_context_load(deadline: RequestDeadline, function, /, *args, **kwargs):
        """Clamp direct slash retrieval to the same whole-operation deadline."""

        remaining = deadline.remaining()
        if remaining <= 0:
            raise AutomationError("The advisor reached its response time limit. Please try again.")
        try:
            return await asyncio.wait_for(asyncio.to_thread(function, *args, **kwargs), timeout=remaining)
        except TimeoutError as exc:
            raise AutomationError("The advisor reached its response time limit. Please try again.") from exc

    def slash_evidence(
        context: object,
        *,
        capability: str,
        arguments: dict[str, object],
        source: str,
        data: object | None = None,
    ) -> dict[str, object]:
        """Attach command metadata without changing the shared evidence shape."""

        # Provenance belongs to the report that was actually retrieved, even
        # when a command substitutes a compact model-facing projection of it.
        envelope = current_evidence_envelope(context, source)
        if data is not None:
            envelope["data"] = data
        envelope.update({"capability": capability, "arguments": arguments, "cache_hits": []})
        return envelope

    def remember_dm_channel(channel: discord.abc.Messageable) -> None:
        channel_id = getattr(channel, "id", None)
        if channel_id is None:
            return
        try:
            persist_discord_channel_id(config, str(channel_id))
        except AutomationError:
            LOGGER.exception("Could not persist the personal Discord DM channel")

    async def report_for_content(
        content: str,
        *,
        requester_id: str,
        context_packet: str | None = None,
        waiver_analysis: bool = False,
        has_attachment: bool = False,
        deadline: RequestDeadline | None = None,
        request_id: str | None = None,
    ) -> tuple[str, bool, str | None, AdvisorRoute | None]:
        if content.startswith("!task ") and not has_attachment:
            task_id = content[6:].strip()
            registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
            task = registry.get(task_id)
            result = await asyncio.to_thread(
                run_scheduled_task,
                config,
                task_id,
                deliver=False,
            )
            return build_report_header(task, result) + result.text, False, result.thread_id, None

        if not waiver_analysis:
            result = await run_advisor(
                config, content, context_packet=context_packet, deadline=deadline,
                requester_id=requester_id, request_id=request_id,
            )
            return advisor_header() + "\n\n" + result.text, True, None, None

        # Dedicated waivers now use the same tool-capable Advisor. The
        # compound capability keeps roster, ownership, and scoring evidence in
        # one model tool call instead of reviving a separate report engine.
        result = await run_advisor(
            config, content, context_packet=context_packet, deadline=deadline or RequestDeadline.start(),
            requester_id=requester_id, request_id=request_id,
        )
        return waiver_header() + "\n\n" + result.text, True, None, None

    def remember_user_message(content: str, *, metadata: dict | None = None) -> None:
        persist_advisor_context_event(
            config,
            kind=DISCORD_USER_MESSAGE,
            content=content,
            metadata={"source": "discord_dm", **(metadata or {})},
        )

    def remember_advisor_response(
        content: str,
        thread_id: str | None,
        *,
        route: AdvisorRoute | None,
    ) -> None:
        persist_advisor_context_event(
            config,
            kind=DISCORD_ASSISTANT_RESPONSE,
            content=content,
            thread_id=thread_id,
            metadata={"source": "discord_dm", **({"route": route.value} if route else {})},
        )

    async def run_and_reply(message: discord.Message, content: str) -> None:
        remember_dm_channel(message.channel)
        async with run_lock:
            await message.channel.send(working_card(), allowed_mentions=discord.AllowedMentions.none())
            deadline = RequestDeadline.start()
            try:
                async with asyncio.timeout(None if content.startswith("!task ") and not message.attachments else deadline.remaining()):
                    attachment_input = await normalize_discord_attachment(message, deadline)
                    user_metadata = None
                    if attachment_input:
                        kind, user_metadata, text = attachment_input
                        source = user_metadata["attachment"]
                        # A voice note without a caption is the owner's request.
                        if kind == "audio" and not content:
                            content = text
                        else:
                            content = f"{content}\n\nAttachment ({kind}; {source['filename']}):\n{text}"
                    context_packet = "" if content.startswith("!task ") and not user_metadata else await asyncio.to_thread(load_advisor_context, config, include_private_evidence=False)
                    await asyncio.to_thread(remember_user_message, content, metadata=user_metadata)
                    report, is_interactive, thread_id, route = await report_for_content(
                        content, context_packet=context_packet,
                        requester_id=str(message.author.id),
                        has_attachment=user_metadata is not None, deadline=deadline,
                        request_id=str(message.id),
                    )
                    if is_interactive:
                        await asyncio.to_thread(remember_advisor_response, report, thread_id, route=route)
                await send_chunks(message.channel, report)
            except AttachmentIntakeError as exc:
                await send_chunks(message.channel, error_card("I couldn’t read that attachment", str(exc)))
            except TimeoutError:
                await send_chunks(message.channel, error_card("I couldn’t complete that task", "The advisor reached its response time limit. Please try again."))
            except (AutomationError, RoutingError) as exc:
                LOGGER.exception("Advisor request failed for Discord message")
                await send_chunks(message.channel, error_card("I couldn’t complete that task", str(exc)))
            except Exception:
                LOGGER.exception("Unexpected Discord task failure")
                await send_chunks(message.channel, error_card("I couldn’t complete that task", "Please try again shortly."))

    async def normalize_discord_attachment(message: discord.Message, deadline: RequestDeadline) -> tuple[str, dict, str] | None:
        attachments = list(message.attachments)
        if not attachments:
            return None
        if len(attachments) > 1:
            raise AttachmentIntakeError("Send one PDF, .txt file, or voice note per message.")
        attachment = attachments[0]
        filename = Path(attachment.filename or "attachment").name
        content_type = attachment.content_type
        validate_attachment_size(classify_attachment(filename, content_type), attachment.size)
        with tempfile.TemporaryDirectory(prefix="fantasy-discord-input-") as temporary:
            destination = Path(temporary) / filename
            try:
                await asyncio.wait_for(attachment.save(destination), timeout=min(15, deadline.remaining(30)))
            except Exception as exc:
                raise AttachmentIntakeError("I couldn’t download that Discord attachment. Please try again.") from exc
            normalized = await normalize_attachment_async(
                destination, filename=filename, content_type=content_type,
                api_key=config.openai_api_key or "",
                audio_model=config.openai_audio_transcription_model,
                document_model=config.openai_document_model, deadline=deadline,
            )
        metadata = {"attachment": {"filename": normalized.filename, "kind": normalized.kind, "content_type": normalized.content_type}}
        return normalized.kind, metadata, normalized.text

    async def handle_watchlist_dm(message: discord.Message, action: str, player: str | None) -> None:
        """Perform an explicit plain-English watchlist request without Codex."""

        remember_dm_channel(message.channel)
        async with run_lock:
            try:
                if action == "list":
                    watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
                    if not watched:
                        await send_chunks(message.channel, watchlist_empty())
                        return
                    await send_chunks(message.channel, watchlist_card(watched))
                    return
                if not player:
                    raise WatchlistError("Include a player name.")
                if action == "add":
                    catalog = await asyncio.to_thread(load_local_player_catalog, config)
                    resolved = resolve_watchlist_player(player, catalog)
                    saved, added = await asyncio.to_thread(add_watchlist_player, watchlist_file(config), resolved)
                    await send_chunks(
                        message.channel,
                        watchlist_change("added" if added else "already_watching", saved),
                    )
                    return
                if action == "remove":
                    watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
                    saved = resolve_saved_watchlist_player(player, watched)
                    removed = await asyncio.to_thread(remove_watchlist_player, watchlist_file(config), saved.player_id)
                    if removed is None:
                        raise WatchlistError("That player is no longer on the watchlist.")
                    await send_chunks(message.channel, watchlist_change("removed", removed))
                    return
                raise WatchlistError(f"Unsupported watchlist action: {action}")
            except (AutomationError, RoutingError, WatchlistError) as exc:
                await send_chunks(message.channel, error_card("I couldn’t update the watchlist", str(exc)))

    async def run_interaction(
        interaction: discord.Interaction,
        content: str,
        *,
        waiver_analysis: bool = False,
    ) -> None:
        """Run a slash-command task in the private bot DM."""

        if str(interaction.user.id) != config.discord_allowed_user_id:
            await interaction.response.send_message(
                private_advisor_only(),
                ephemeral=True,
            )
            return
        remember_dm_channel(interaction.channel)
        await interaction.response.defer()
        async with run_lock:
            try:
                normal = not content.startswith("!task ")
                deadline = RequestDeadline.start() if normal else None
                async with asyncio.timeout(deadline.remaining() if deadline else None):
                    context_packet = "" if content.startswith("!task ") else await asyncio.to_thread(load_advisor_context, config, include_private_evidence=False)
                    await asyncio.to_thread(remember_user_message, content)
                    report, is_interactive, thread_id, route = await report_for_content(
                        content, context_packet=context_packet,
                        requester_id=str(interaction.user.id),
                        waiver_analysis=waiver_analysis, deadline=deadline,
                        request_id=str(getattr(interaction, "id", f"interaction-{interaction.user.id}")),
                    )
                    if is_interactive:
                        await asyncio.to_thread(remember_advisor_response, report, thread_id, route=route)
                chunks = split_discord_message(report, limit=1900)
                # User-installed interactions have a bounded follow-up budget.
                # Keep the response complete for normal reports and make an
                # unusually large report fail visibly instead of silently
                # dropping its tail.
                if len(chunks) > 5:
                    chunks = chunks[:4] + [response_limit_notice()]
                await interaction.edit_original_response(content=chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(
                        chunk,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except (AutomationError, RoutingError) as exc:
                LOGGER.exception("Advisor request failed for Discord command")
                await interaction.edit_original_response(
                    content=compact_interaction_error("I couldn’t complete that task", exc)
                )
            except Exception:
                LOGGER.exception("Unexpected Discord command failure")
                await interaction.edit_original_response(
                    content=error_card("I couldn’t complete that task", "Please try again shortly.")
                )

    @command_tree.command(name="ask", description="Ask a football or fantasy question")
    @app_commands.describe(prompt="Ask about news, your team, waivers, or a player")
    @app_commands.allowed_installs(users=True, guilds=False)
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    async def ask_command(interaction: discord.Interaction, prompt: str) -> None:
        if not prompt.strip():
            await interaction.response.send_message(
                error_card("Add a question", "Try `/ask` followed by what you want to know."),
                ephemeral=True,
            )
            return
        await run_interaction(interaction, prompt.strip())

    @command_tree.command(
        name="analyze-waivers",
        description="Analyze the full waiver shortlist and roster-aware swap signals",
    )
    @app_commands.allowed_installs(users=True, guilds=False)
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    async def analyze_waivers_command(interaction: discord.Interaction) -> None:
        await run_interaction(
            interaction,
            WAIVER_ANALYSIS_REQUEST,
            waiver_analysis=True,
        )

    @command_tree.command(
        name="rotation",
        description="Plan protected-core moves around the next four fixtures",
    )
    @app_commands.allowed_installs(users=True, guilds=False)
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    async def rotation_command(interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != config.discord_allowed_user_id:
            await interaction.response.send_message(private_advisor_only(), ephemeral=True)
            return
        remember_dm_channel(interaction.channel)
        await interaction.response.defer()
        deadline = RequestDeadline.start()
        try:
            async with run_lock:
                fixture_schedule = await bounded_context_load(
                    deadline,
                    load_fixture_schedule,
                    config,
                    now=discord.utils.utcnow(),
                )
                context = await bounded_context_load(
                    deadline,
                    get_rotation_context,
                    manager_id=EXPECTED_MANAGER_ID,
                    fixture_schedule=fixture_schedule,
                )
                result = await finalize_advisor_from_evidence(
                    config,
                    command="/rotation",
                    question="Plan protected-core moves around the next four fixtures.",
                    evidence=slash_evidence(
                        context, capability="get_rotation_context", arguments={}, source="Fantasy rotation context",
                    ),
                    mandatory_web=True,
                    deadline=deadline,
                    partial_text=(
                        "🔄 **Rotation · current Fantasy evidence retrieved**\n"
                        "I couldn’t verify current public role and availability information, so I’m not recommending a pickup or trade target. HOLD rather than act on unverified news."
                    ),
                    command_instructions=(
                        "Use the deterministic protected core, roster, fixtures, pickup targets, trade targets, and drop candidates only. "
                        "Research current role, availability, injury, and club facts before recommending any incoming target. "
                        "An honest HOLD is preferred to a marginal move. Never combine a pickup with a drop automatically."
                    ),
                )
            await edit_interaction_with_chunks(interaction, result.text)
        except (AutomationError, SleeperDataError) as exc:
            LOGGER.exception("Could not build a rotation report")
            await interaction.edit_original_response(
                content=compact_interaction_error("Couldn’t build the rotation report", exc)
            )
        except Exception:
            LOGGER.exception("Unexpected failure building a rotation report")
            await interaction.edit_original_response(
                content=error_card("Couldn’t build the rotation report", "Please try again shortly.")
            )

    @command_tree.command(name="tasks", description="List the registered fantasy advisor tasks")
    @app_commands.allowed_installs(users=True, guilds=False)
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    async def tasks_command(interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != config.discord_allowed_user_id:
            await interaction.response.send_message(
                private_advisor_only(),
                ephemeral=True,
            )
            return
        remember_dm_channel(interaction.channel)
        registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
        LOGGER.info("Rendering mobile /tasks menu for the allowlisted Discord user")
        await interaction.response.send_message(
            task_menu(registry.tasks),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @command_tree.command(name="task", description="Run one registered task now")
    @app_commands.describe(task_id="The registered task ID to run")
    @app_commands.allowed_installs(users=True, guilds=False)
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    async def task_command(interaction: discord.Interaction, task_id: str) -> None:
        try:
            registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
            registry.get(task_id.strip())
        except AutomationError as exc:
            await interaction.response.send_message(error_card("That report isn’t available", str(exc)), ephemeral=True)
            return
        await run_interaction(interaction, f"!task {task_id.strip()}")

    watch_group = app_commands.Group(
        name="watch",
        description="Manage the private Premier League player watchlist",
        allowed_installs=app_commands.AppInstallationType(user=True, guild=False),
        allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
    )

    async def ensure_private_user(interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) == config.discord_allowed_user_id:
            return True
        await interaction.response.send_message(
            private_advisor_only(), ephemeral=True
        )
        return False

    @watch_group.command(name="add", description="Add a Sleeper EPL player to your watchlist")
    @app_commands.describe(player="Player name, optionally followed by club")
    async def watch_add_command(interaction: discord.Interaction, player: str) -> None:
        if not await ensure_private_user(interaction):
            return
        if not player.strip():
            await interaction.response.send_message(
                error_card("Add a player name", "Try `/watch add player`."),
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        try:
            catalog = await asyncio.to_thread(load_local_player_catalog, config)
            resolved = resolve_watchlist_player(player, catalog)
            saved, added = await asyncio.to_thread(add_watchlist_player, watchlist_file(config), resolved)
            await interaction.edit_original_response(
                content=watchlist_change("added" if added else "already_watching", saved)
            )
        except (AutomationError, WatchlistError) as exc:
            await interaction.edit_original_response(content=compact_interaction_error("Couldn’t update the watchlist", exc))

    @watch_group.command(name="remove", description="Remove a player from your watchlist")
    @app_commands.describe(player="Watched player name, optionally followed by club")
    async def watch_remove_command(interaction: discord.Interaction, player: str) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        try:
            watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
            resolved = resolve_saved_watchlist_player(player, watched)
            removed = await asyncio.to_thread(remove_watchlist_player, watchlist_file(config), resolved.player_id)
            if removed is None:
                raise WatchlistError("That player is no longer on the watchlist.")
            await interaction.edit_original_response(content=watchlist_change("removed", removed))
        except (WatchlistError, WatchlistResolutionError) as exc:
            await interaction.edit_original_response(content=compact_interaction_error("Couldn’t update the watchlist", exc))

    @watch_group.command(name="list", description="List your watched Sleeper EPL players")
    async def watch_list_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        try:
            watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
            if not watched:
                content = watchlist_empty()
            else:
                content = watchlist_card(watched)
            await interaction.response.send_message(content, allowed_mentions=discord.AllowedMentions.none())
        except WatchlistError as exc:
            await interaction.response.send_message(compact_interaction_error("Couldn’t read the watchlist", exc), ephemeral=True)

    @watch_group.command(name="stats", description="Fetch current Sleeper stats for every watched player")
    async def watch_stats_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        try:
            watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
            if not watched:
                await interaction.edit_original_response(content=watchlist_empty())
                return
            async with run_lock:
                report = await asyncio.to_thread(
                    get_watchlist_stats,
                    watched,
                    include_trends=True,
                    include_previous_season=True,
                )
            await edit_interaction_with_chunks(interaction, watchlist_stats_card(report))
        except (AutomationError, SleeperDataError, WatchlistError) as exc:
            LOGGER.exception("Could not load current Sleeper watchlist stats")
            await interaction.edit_original_response(
                content=compact_interaction_error("Couldn’t load watchlist stats", exc)
            )
        except Exception:
            LOGGER.exception("Unexpected failure loading current Sleeper watchlist stats")
            await interaction.edit_original_response(
                content=error_card("Couldn’t load watchlist stats", "Please try again shortly.")
            )

    @watch_group.command(name="outlook", description="Analyze current news and expert outlooks for watched players")
    async def watch_outlook_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        deadline = RequestDeadline.start()
        try:
            watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
            if not watched:
                await interaction.edit_original_response(content=watchlist_empty())
                return
            selected = watched[:12]
            omitted = len(watched) - len(selected)
            async with run_lock:
                report = await bounded_context_load(deadline, get_watchlist_stats, selected)
                data = json.loads(watchlist_outlook_context(report))
                data["watchlist_omitted_count"] = omitted
                result = await finalize_advisor_from_evidence(
                    config,
                    command="/watch outlook",
                    question="Give me a current outlook for every player on my watchlist.",
                    evidence=slash_evidence(
                        report, capability="get_watchlist_stats", arguments={}, source="Fantasy watchlist and current Sleeper statistics", data=data,
                    ),
                    mandatory_web=True,
                    deadline=deadline,
                    partial_text=(
                        "👀 **Watchlist outlook · current Fantasy evidence retrieved**\n"
                        "I couldn’t verify the current public outlook right now, so I’m not adding role or availability claims beyond the current watchlist/stat facts."
                        + (f"\n\n*{omitted} watchlist player(s) were not covered because this command is limited to 12 per run.*" if omitted else "")
                    ),
                    command_instructions=(
                        "Discuss only the canonical watched players in the supplied evidence. Research current role, availability, injury, and minutes outlook. "
                        "If watchlist_omitted_count is positive, explicitly disclose it. Do not recommend a player who is not currently watched."
                    ),
                )
            await edit_interaction_with_chunks(interaction, result.text)
        except (AutomationError, SleeperDataError, WatchlistError) as exc:
            LOGGER.exception("Could not load current watchlist outlook")
            await interaction.edit_original_response(
                content=compact_interaction_error("Couldn’t analyze the watchlist", exc)
            )
        except Exception:
            LOGGER.exception("Unexpected failure loading current watchlist outlook")
            await interaction.edit_original_response(
                content=error_card("Couldn’t analyze the watchlist", "Please try again shortly.")
            )

    @watch_group.command(name="recommend", description="Suggest manual watchlist pickup/drop swaps for your roster")
    async def watch_recommend_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        deadline = RequestDeadline.start()
        try:
            watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
            if not watched:
                await interaction.edit_original_response(content=watchlist_empty())
                return
            async with run_lock:
                context = await bounded_context_load(
                    deadline,
                    load_current_watchlist_recommendation_context,
                    watched,
                    manager_id=EXPECTED_MANAGER_ID,
                )
                data = json.loads(watchlist_recommendation_context(context))
                result = await finalize_advisor_from_evidence(
                    config,
                    command="/watch recommend",
                    question="Assess my watched players against my current roster and identify only the best manual pickup/drop opportunities.",
                    evidence=slash_evidence(
                        context, capability="get_watchlist_recommendation_context", arguments={}, source="Fantasy watchlist recommendation context", data=data,
                    ),
                    mandatory_web=True,
                    deadline=deadline,
                    partial_text=(
                        "🎯 **Watchlist recommendations · current Fantasy evidence retrieved**\n"
                        "I couldn’t verify current public role and availability information, so HOLD rather than make an actionable pickup recommendation."
                    ),
                    command_instructions=(
                        "Use the supplied canonical watchlist, current roster, and same-position signals. "
                        "Recommend at most three manual opportunities, never mutate the watchlist, and verify every acquisition target's current role and availability. "
                        "Do not describe a rostered player as available."
                    ),
                )
            await edit_interaction_with_chunks(interaction, result.text)
        except (AutomationError, SleeperDataError, WatchlistError) as exc:
            LOGGER.exception("Could not load watchlist recommendations")
            await interaction.edit_original_response(
                content=compact_interaction_error("Couldn’t recommend watchlist moves", exc)
            )
        except Exception:
            LOGGER.exception("Unexpected failure loading watchlist recommendations")
            await interaction.edit_original_response(
                content=error_card("Couldn’t recommend watchlist moves", "Please try again shortly.")
            )

    command_tree.add_command(watch_group)

    injury_group = app_commands.Group(
        name="injury",
        description="Review Sleeper injury flags and playing-time opportunities",
        allowed_installs=app_commands.AppInstallationType(user=True, guild=False),
        allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
    )

    @injury_group.command(name="opportunities", description="Find EPL injuries and likely playing-time beneficiaries")
    async def injury_opportunities_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        deadline = RequestDeadline.start()
        try:
            async with run_lock:
                context = await bounded_context_load(
                    deadline, get_injury_opportunity_context, manager_id=EXPECTED_MANAGER_ID,
                )
                timeline_context = injury_timeline_research_context(context)
                researched_player_ids = [str(player["player_id"]) for player in timeline_context["injured_players"]]
                timeline_trace = {
                    "timeline_research_selected_count": len(researched_player_ids),
                    "timeline_research_player_ids": researched_player_ids,
                    "timeline_research_completed": False,
                    "timeline_research_web_used": False,
                    "timeline_research_retry_used": False,
                    "web_search_used": False,
                }
                research = None
                research_error = None
                # Keep this single structured public-research pass inside the
                # command deadline and leave enough time to render its answer.
                # The terminal slash finalizer consumes the remaining hard
                # request budget directly, so this bounded research pass does
                # not need to reserve a second, unused final-answer window.
                research_budget = min(60.0, deadline.remaining(35.0))
                if research_budget <= 0:
                    research_error = "Current public timetable research could not start before the response deadline."
                else:
                    try:
                        research = await asyncio.wait_for(
                            asyncio.to_thread(
                                run_injury_web_briefing,
                                config,
                                live_context=json.dumps(timeline_context, ensure_ascii=False, separators=(",", ":")),
                                timeout_seconds=research_budget,
                            ),
                            timeout=research_budget,
                        )
                        timeline_trace.update({
                            "timeline_research_completed": True,
                            "timeline_research_web_used": research.web_search_used,
                            "timeline_research_retry_used": research.retry_used,
                            "web_search_used": research.web_search_used,
                        })
                    except (AutomationError, TimeoutError) as exc:
                        LOGGER.warning("Current injury timeline research was unavailable; returning Sleeper inventory", exc_info=True)
                        research_error = "Current public timetable research was unavailable."
                report = render_injury_opportunities(
                    context,
                    research,
                    research_error=research_error,
                    researched_player_ids=researched_player_ids,
                )
                evidence = slash_evidence(
                    context,
                    capability="get_injury_opportunity_context",
                    arguments={},
                    source="Fantasy injury opportunity context",
                    data={
                        "injury_inventory": context.payload,
                        "priority_timeline_research": (
                            {"injuries": list(research.injuries), "opportunities": list(research.opportunities)}
                            if research is not None else None
                        ),
                    },
                )
                evidence["status"] = "complete" if research is not None else "unavailable"
                evidence["sources"].append({
                    "source": "Current public injury timeline research",
                    "retrieved_at": context.retrieved_at,
                    "stale": False,
                })
                result = await finalize_advisor_from_evidence(
                    config,
                    command="/injury opportunities",
                    question="Assess the current injury board for buy-low timing and credible playing-time opportunities.",
                    evidence=evidence,
                    mandatory_web=False,
                    web_enabled=False,
                    deadline=deadline,
                    partial_text=report,
                    trace_fields=timeline_trace,
                    command_instructions=(
                        "Use the supplied full Sleeper injury inventory and the bounded, already-completed public timeline research. "
                        "Do not perform another general injury search or invent a return date. Surface only supported buy-low or beneficiary implications; otherwise HOLD."
                    ),
                )
                final_text = report if result.trace["result_status"] != "complete" else (
                    report + "\n\n🧭 **Advisor assessment**\n" + result.text
                )
            await edit_injury_interaction(interaction, final_text)
        except SleeperDataError as exc:
            LOGGER.exception("Could not load the current Sleeper injury board")
            await interaction.edit_original_response(
                content=compact_interaction_error("Couldn’t load injury opportunities", exc)
            )
        except Exception:
            LOGGER.exception("Unexpected failure loading injury opportunities")
            await interaction.edit_original_response(
                content=error_card("Couldn’t load injury opportunities", "Please try again shortly.")
            )

    command_tree.add_command(injury_group)

    trade_group = app_commands.Group(
        name="trade",
        description="Find a realistic, evidence-backed manual trade package",
        allowed_installs=app_commands.AppInstallationType(user=True, guild=False),
        allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
    )

    @trade_group.command(name="propose", description="Propose a realistic manual roster-improving trade")
    async def trade_propose_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        deadline = RequestDeadline.start()
        try:
            async with run_lock:
                fixture_schedule = await bounded_context_load(deadline, load_persisted_fixture_schedule, config)
                context = await bounded_context_load(
                    deadline,
                    get_trade_context,
                    manager_id=EXPECTED_MANAGER_ID,
                    fixture_schedule=fixture_schedule,
                )
                candidates = context.payload.get("candidate_packages")
                if not isinstance(candidates, list) or not candidates:
                    await interaction.edit_original_response(content=no_viable_trade_package(context))
                    return
                result = await finalize_advisor_from_evidence(
                    config,
                    command="/trade propose",
                    question="Choose the strongest current manual trade proposal for Los Blancos.",
                    evidence=slash_evidence(
                        context, capability="get_trade_context", arguments={"you_send": None, "you_receive": None}, source="Fantasy trade proposal context",
                    ),
                    mandatory_web=True,
                    deadline=deadline,
                    partial_text=(
                        "🛑 **No actionable trade proposal today**\n"
                        "Current Fantasy package evidence was retrieved, but incoming players could not be publicly verified. HOLD rather than make an unverified offer."
                    ),
                    command_instructions=(
                        "Choose only a candidate package supplied by the deterministic engine, or recommend no trade. "
                        "Verify every incoming player’s current availability/injury and material role/minutes outlook before finalizing. "
                        "Never invent a package, player, FAAB term, or claim a Sleeper trade occurred."
                    ),
                )
            await edit_interaction_with_chunks(interaction, result.text)
        except (AutomationError, SleeperDataError) as exc:
            LOGGER.exception("Could not build a trade proposal")
            await interaction.edit_original_response(
                content=compact_interaction_error("Couldn’t build a trade proposal", exc)
            )
        except Exception:
            LOGGER.exception("Unexpected failure building a trade proposal")
            await interaction.edit_original_response(
                content=error_card("Couldn’t build a trade proposal", "Please try again shortly.")
            )

    command_tree.add_command(trade_group)

    guardian_group = app_commands.Group(
        name="guardian",
        description="Acknowledge or check private lineup alerts",
        allowed_installs=app_commands.AppInstallationType(user=True, guild=False),
        allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
    )

    @guardian_group.command(name="done", description="Acknowledge every current lineup alert")
    async def guardian_done_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        try:
            acknowledged = await asyncio.to_thread(acknowledge_active_events, config, now=discord.utils.utcnow())
            await interaction.response.send_message(guardian_acknowledged(acknowledged))
        except AutomationError as exc:
            await interaction.response.send_message(
                compact_interaction_error("Couldn’t update Deadline Guardian", exc), ephemeral=True
            )

    @guardian_group.command(name="status", description="Show your upcoming lineup-alert acknowledgement status")
    async def guardian_status_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        try:
            events = await asyncio.to_thread(active_events, config, now=discord.utils.utcnow())
            await interaction.response.send_message(guardian_status(events))
        except AutomationError as exc:
            await interaction.response.send_message(
                compact_interaction_error("Couldn’t read Deadline Guardian", exc), ephemeral=True
            )

    command_tree.add_command(guardian_group)

    gameweek_group = app_commands.Group(
        name="gameweek",
        description="Prepare the next gameweek or recap the last one",
        allowed_installs=app_commands.AppInstallationType(user=True, guild=False),
        allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
    )

    @gameweek_group.command(name="prepare", description="Analyze your next gameweek lineup and key opponents")
    async def gameweek_prepare_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        deadline = RequestDeadline.start()
        try:
            async with run_lock:
                context = await bounded_context_load(
                    deadline,
                    get_gameweek_prepare_context,
                    manager_id=EXPECTED_MANAGER_ID,
                )
                result = await finalize_advisor_from_evidence(
                    config,
                    command="/gameweek prepare",
                    question="Prepare my next gameweek lineup and key opponents.",
                    evidence=slash_evidence(
                        context, capability="get_gameweek_context", arguments={"mode": "prepare"}, source="Fantasy gameweek prepare context",
                    ),
                    mandatory_web=True,
                    deadline=deadline,
                    partial_text=(
                        "🗓️ **Gameweek preparation · current Fantasy evidence retrieved**\n"
                        "Current roster and fixture facts are available, but public team news could not be verified. Treat lineup advice as provisional; do not rely on unverified injury or role assumptions."
                    ),
                    command_instructions=(
                        "Use only current Los Blancos roster players in start/bench guidance. "
                        "Research material injury, availability, role, and team-news facts before presenting them as current."
                    ),
                )
            await edit_interaction_with_chunks(interaction, result.text)
        except (AutomationError, SleeperDataError) as exc:
            LOGGER.exception("Could not prepare gameweek report")
            await interaction.edit_original_response(
                content=compact_interaction_error("Couldn’t prepare the gameweek", exc)
            )
        except Exception:
            LOGGER.exception("Unexpected failure preparing gameweek report")
            await interaction.edit_original_response(
                content=error_card("Couldn’t prepare the gameweek", "Please try again shortly.")
            )

    @gameweek_group.command(name="recap", description="Recap your latest completed gameweek and league standouts")
    async def gameweek_recap_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        deadline = RequestDeadline.start()
        try:
            async with run_lock:
                context = await bounded_context_load(
                    deadline,
                    get_gameweek_recap_context,
                    manager_id=EXPECTED_MANAGER_ID,
                )
                result = await finalize_advisor_from_evidence(
                    config,
                    command="/gameweek recap",
                    question="Recap my latest completed gameweek and league standouts.",
                    evidence=slash_evidence(
                        context, capability="get_gameweek_context", arguments={"mode": "recap"}, source="Fantasy gameweek recap context",
                    ),
                    mandatory_web=False,
                    deadline=deadline,
                    partial_text=(
                        "📬 **Gameweek recap · current Fantasy evidence retrieved**\n"
                        "I couldn’t complete the recap synthesis right now. Please try again."
                    ),
                    command_instructions=(
                        "Summarize only the supplied verified completed-gameweek data. Public research is optional and only needed for a material football explanation. "
                        "Do not load prepare context or invent a current H2H matchup."
                    ),
                )
            await edit_interaction_with_chunks(interaction, result.text)
        except (AutomationError, SleeperDataError) as exc:
            LOGGER.exception("Could not recap gameweek report")
            await interaction.edit_original_response(
                content=compact_interaction_error("Couldn’t recap the gameweek", exc)
            )
        except Exception:
            LOGGER.exception("Unexpected failure recapping gameweek report")
            await interaction.edit_original_response(
                content=error_card("Couldn’t recap the gameweek", "Please try again shortly.")
            )

    command_tree.add_command(gameweek_group)

    player_catalog_group = app_commands.Group(
        name="player_catalog",
        description="Refresh the private Sleeper player catalog",
        allowed_installs=app_commands.AppInstallationType(user=True, guild=False),
        allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
    )

    @player_catalog_group.command(name="update", description="Refresh the local Sleeper EPL player catalog")
    async def player_catalog_update_command(interaction: discord.Interaction) -> None:
        if not await ensure_private_user(interaction):
            return
        await interaction.response.defer()
        async with run_lock:
            try:
                refreshed = await asyncio.to_thread(update_player_catalog, config)
                await interaction.edit_original_response(content=player_catalog_updated(refreshed))
            except AutomationError as exc:
                await interaction.edit_original_response(
                    content=compact_interaction_error("Couldn’t update the player catalog", exc)
                )

    command_tree.add_command(player_catalog_group)

    @client.event
    async def on_ready() -> None:
        nonlocal command_sync_complete
        LOGGER.info("Fantasy Discord bot connected as %s", client.user)
        schedule_online_presence()
        persist_discord_ready_state(config)
        if not command_sync_complete:
            try:
                synced = await command_tree.sync()
                command_sync_complete = True
                LOGGER.info("Synced %d private Discord commands", len(synced))
            except Exception:
                LOGGER.exception("Could not sync private Discord commands")

    @client.event
    async def on_resumed() -> None:
        schedule_online_presence()
        LOGGER.info("Fantasy Discord gateway session resumed")

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is not None or not isinstance(message.channel, discord.DMChannel):
            return
        if str(message.author.id) != config.discord_allowed_user_id:
            LOGGER.warning("Ignoring DM from non-allowlisted Discord user %s", message.author.id)
            return
        try:
            if not claim_discord_message(config, str(message.id)):
                LOGGER.info("Ignoring duplicate Discord message %s", message.id)
                return
        except AutomationError:
            # Fail closed: continuing without a durable claim could emit two
            # advisor replies if Discord replays this event.
            LOGGER.exception("Could not claim Discord message %s", message.id)
            return
        caption = message.content.strip()
        if message.attachments:
            await run_and_reply(message, caption)
            return
        content = caption
        if not content:
            return
        # Discord may emit the rendered slash-command message through the DM
        # message event as well as its interaction event.  The command handler
        # is the authoritative route for these messages; letting this fallback
        # continue would run the grounded freeform Advisor in parallel with a
        # specialist command.
        if content.startswith("/"):
            return
        if content.casefold() in {"!help", "help"}:
            await send_chunks(
                message.channel,
                help_menu(),
            )
            return
        if content.casefold() == "!tasks":
            try:
                registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
                await send_chunks(message.channel, task_menu(registry.tasks))
            except AutomationError as exc:
                await send_chunks(message.channel, error_card("I couldn’t load your reports", str(exc)))
            return
        await run_and_reply(message, content)

    return client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the DM-only fantasy Discord bot")
    parser.add_argument("--log-level", default=None, help="override FANTASY_LOG_LEVEL")
    args = parser.parse_args(argv)
    try:
        config = AppConfig.from_environment()
        config.require_discord()
    except AutomationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    logging.basicConfig(
        level=getattr(
            logging,
            (args.log_level or os.environ.get("FANTASY_LOG_LEVEL", "INFO")).upper(),
            logging.INFO,
        ),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOGGER.info("Fantasy Discord worker starting runtime_sha=%s", os.environ.get("FANTASY_RUNTIME_SHA", "unknown"))
    client = build_client(config)
    client.run(config.discord_bot_token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
