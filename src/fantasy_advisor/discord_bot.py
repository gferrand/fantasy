"""DM-only Discord gateway for on-demand fantasy advisor tasks."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys
import tempfile

import discord
from discord import app_commands

from .automation import (
    AppConfig,
    AutomationError,
    build_report_header,
    load_current_epl_player_index,
    load_advisor_context,
    persist_discord_channel_id,
    persist_discord_ready_state,
    persist_advisor_context_event,
    load_registry,
    run_interactive_task,
    run_scheduled_task,
    split_discord_message,
    watchlist_file,
)
from .attachment_intake import (
    AttachmentIntakeError,
    normalize_attachment,
)
from .context_store import DISCORD_ASSISTANT_RESPONSE, DISCORD_USER_MESSAGE
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

        text = f"{prefix}: {exc}"
        if len(text) <= 1900:
            return text
        return text[:1850].rstrip() + "\n[diagnostic truncated]"

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
        context_packet: str | None = None,
        waiver_analysis: bool = False,
    ) -> tuple[str, bool, str | None]:
        if content.startswith("!task "):
            task_id = content[6:].strip()
            registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
            task = registry.get(task_id)
            result = await asyncio.to_thread(
                run_scheduled_task,
                config,
                task_id,
                deliver=False,
            )
            return build_report_header(task, result) + result.text, False, result.thread_id

        result = await asyncio.to_thread(
            run_interactive_task,
            config,
            content,
            context_packet=context_packet,
            waiver_analysis=waiver_analysis,
        )
        if waiver_analysis:
            return (
                "🏟️ **Los Blancos — Waiver Wire**\n"
                "📱 *Phone-friendly view · manual review only*\n\n"
                f"{result.text}",
                True,
                result.thread_id,
            )
        return (
            f"**On-demand fantasy advisor** · Codex task `"
            f"{result.thread_id or 'local'}`\n\n{result.text}",
            True,
            result.thread_id,
        )

    def remember_user_message(content: str, *, metadata: dict | None = None) -> None:
        persist_advisor_context_event(
            config,
            kind=DISCORD_USER_MESSAGE,
            content=content,
            metadata={"source": "discord_dm", **(metadata or {})},
        )

    def remember_advisor_response(content: str, thread_id: str | None) -> None:
        persist_advisor_context_event(
            config,
            kind=DISCORD_ASSISTANT_RESPONSE,
            content=content,
            thread_id=thread_id,
            metadata={"source": "discord_dm"},
        )

    async def run_and_reply(
        message: discord.Message,
        content: str,
        *,
        user_metadata: dict | None = None,
    ) -> None:
        remember_dm_channel(message.channel)
        async with run_lock:
            await message.channel.send(
                "Starting a local Codex task. I’ll DM the result here when it finishes.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            try:
                # Build context before recording the current prompt so the
                # request is supplied exactly once to the new Codex task.
                context_packet = "" if content.startswith("!task ") else load_advisor_context(config)
                remember_user_message(content, metadata=user_metadata)
                report, is_interactive, thread_id = await report_for_content(
                    content,
                    context_packet=context_packet,
                )
                if is_interactive:
                    remember_advisor_response(report, thread_id)
                await send_chunks(message.channel, report)
            except AutomationError as exc:
                LOGGER.exception("Codex task failed for Discord message")
                await send_chunks(message.channel, f"I couldn’t complete that task: {exc}")
            except Exception:
                LOGGER.exception("Unexpected Discord task failure")
                await send_chunks(message.channel, "I couldn’t complete that task because of an unexpected local error.")

    async def normalize_discord_attachment(
        message: discord.Message,
    ) -> tuple[str, dict, str] | None:
        """Download one attachment privately, normalize it, and remove it immediately."""

        attachments = list(message.attachments)
        if not attachments:
            return None
        if len(attachments) > 1:
            raise AttachmentIntakeError("Send one PDF, .txt file, or voice note per message.")
        attachment = attachments[0]
        filename = Path(attachment.filename or "attachment").name
        content_type = attachment.content_type
        await message.channel.send(
            "Processing your attachment…",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        with tempfile.TemporaryDirectory(prefix="fantasy-discord-input-") as temporary:
            destination = Path(temporary) / filename
            try:
                await attachment.save(destination)
            except Exception as exc:
                raise AttachmentIntakeError("I couldn’t download that Discord attachment. Please try again.") from exc
            normalized = await asyncio.to_thread(
                normalize_attachment,
                destination,
                filename=filename,
                content_type=content_type,
                api_key=config.openai_api_key or "",
                audio_model=config.openai_audio_transcription_model,
                document_model=config.openai_document_model,
            )
        metadata = {
            "attachment": {
                "filename": normalized.filename,
                "kind": normalized.kind,
                "content_type": normalized.content_type,
            }
        }
        return normalized.kind, metadata, normalized.text

    async def handle_watchlist_dm(message: discord.Message, action: str, player: str | None) -> None:
        """Perform an explicit plain-English watchlist request without Codex."""

        remember_dm_channel(message.channel)
        async with run_lock:
            try:
                if action == "list":
                    watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
                    if not watched:
                        await send_chunks(message.channel, "Your watchlist is empty. Say “add [player] to my watchlist” to begin.")
                        return
                    entries = "\n".join(
                        f"• **{entry.name}** — {entry.club} ({'/'.join(entry.positions) or 'position unavailable'})"
                        for entry in watched
                    )
                    await send_chunks(message.channel, f"**Your watchlist ({len(watched)})**\n{entries}")
                    return
                if not player:
                    raise WatchlistError("Include a player name.")
                if action == "add":
                    index = await asyncio.to_thread(load_current_epl_player_index, config)
                    resolved = resolve_watchlist_player(player, index)
                    saved, added = await asyncio.to_thread(add_watchlist_player, watchlist_file(config), resolved)
                    verb = "Added" if added else "Already watching"
                    await send_chunks(
                        message.channel,
                        f"{verb}: **{saved.name}** — {saved.club} ({'/'.join(saved.positions) or 'position unavailable'}).",
                    )
                    return
                if action == "remove":
                    watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
                    saved = resolve_saved_watchlist_player(player, watched)
                    removed = await asyncio.to_thread(remove_watchlist_player, watchlist_file(config), saved.player_id)
                    if removed is None:
                        raise WatchlistError("That player is no longer on the watchlist.")
                    await send_chunks(message.channel, f"Removed **{removed.name}** from the watchlist.")
                    return
                raise WatchlistError(f"Unsupported watchlist action: {action}")
            except (AutomationError, WatchlistError) as exc:
                await send_chunks(message.channel, f"I couldn’t update the watchlist: {exc}")

    async def run_interaction(
        interaction: discord.Interaction,
        content: str,
        *,
        waiver_analysis: bool = False,
    ) -> None:
        """Run a slash-command task in the private bot DM."""

        if str(interaction.user.id) != config.discord_allowed_user_id:
            await interaction.response.send_message(
                "This private fantasy advisor is not enabled for this Discord account.",
                ephemeral=True,
            )
            return
        remember_dm_channel(interaction.channel)
        await interaction.response.defer()
        async with run_lock:
            try:
                context_packet = "" if content.startswith("!task ") else load_advisor_context(config)
                remember_user_message(content)
                report, is_interactive, thread_id = await report_for_content(
                    content,
                    context_packet=context_packet,
                    waiver_analysis=waiver_analysis,
                )
                if is_interactive:
                    remember_advisor_response(report, thread_id)
                chunks = split_discord_message(report, limit=1900)
                # User-installed interactions have a bounded follow-up budget.
                # Keep the response complete for normal reports and make an
                # unusually large report fail visibly instead of silently
                # dropping its tail.
                if len(chunks) > 5:
                    chunks = chunks[:4] + [
                        "\n\n[The report exceeded Discord’s user-install response limit. "
                        "Run the same task locally to read the full result.]"
                    ]
                await interaction.edit_original_response(content=chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(
                        chunk,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except AutomationError as exc:
                LOGGER.exception("Codex task failed for Discord command")
                await interaction.edit_original_response(
                    content=compact_interaction_error("I couldn’t complete that task", exc)
                )
            except Exception:
                LOGGER.exception("Unexpected Discord command failure")
                await interaction.edit_original_response(
                    content="I couldn’t complete that task because of an unexpected local error."
                )

    @command_tree.command(name="ask", description="Run a read-only fantasy advisor task")
    @app_commands.describe(prompt="What should the local Codex fantasy advisor research?")
    @app_commands.allowed_installs(users=True, guilds=False)
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    async def ask_command(interaction: discord.Interaction, prompt: str) -> None:
        if not prompt.strip():
            await interaction.response.send_message("Include a question after `/ask`.", ephemeral=True)
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

    @command_tree.command(name="tasks", description="List the registered fantasy advisor tasks")
    @app_commands.allowed_installs(users=True, guilds=False)
    @app_commands.allowed_contexts(guilds=False, dms=True, private_channels=False)
    async def tasks_command(interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != config.discord_allowed_user_id:
            await interaction.response.send_message(
                "This private fantasy advisor is not enabled for this Discord account.",
                ephemeral=True,
            )
            return
        remember_dm_channel(interaction.channel)
        registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
        tasks = "\n".join(f"`{task.id}` — {task.name}" for task in registry.tasks)
        await interaction.response.send_message(
            f"Registered tasks:\n{tasks}",
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
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await run_interaction(interaction, f"!task {task_id.strip()}")

    watch_group = app_commands.Group(
        name="watch",
        description="Manage the private Premier League player watchlist",
        allowed_installs=app_commands.AppInstallationType(user=True, guild=False),
        allowed_contexts=app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False),
    )

    async def ensure_watchlist_user(interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) == config.discord_allowed_user_id:
            return True
        await interaction.response.send_message(
            "This private fantasy advisor is not enabled for this Discord account.", ephemeral=True
        )
        return False

    @watch_group.command(name="add", description="Add a current Premier League player to your watchlist")
    @app_commands.describe(player="Player name, optionally followed by club")
    async def watch_add_command(interaction: discord.Interaction, player: str) -> None:
        if not await ensure_watchlist_user(interaction):
            return
        if not player.strip():
            await interaction.response.send_message("Include a player name after `/watch add`.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            index = await asyncio.to_thread(load_current_epl_player_index, config)
            resolved = resolve_watchlist_player(player, index)
            saved, added = await asyncio.to_thread(add_watchlist_player, watchlist_file(config), resolved)
            action = "Added" if added else "Already watching"
            positions = "/".join(saved.positions) or "position unavailable"
            await interaction.edit_original_response(
                content=f"{action}: **{saved.name}** — {saved.club} ({positions})."
            )
        except (AutomationError, WatchlistError) as exc:
            await interaction.edit_original_response(content=compact_interaction_error("Couldn’t update the watchlist", exc))

    @watch_group.command(name="remove", description="Remove a player from your watchlist")
    @app_commands.describe(player="Watched player name, optionally followed by club")
    async def watch_remove_command(interaction: discord.Interaction, player: str) -> None:
        if not await ensure_watchlist_user(interaction):
            return
        await interaction.response.defer()
        try:
            watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
            resolved = resolve_saved_watchlist_player(player, watched)
            removed = await asyncio.to_thread(remove_watchlist_player, watchlist_file(config), resolved.player_id)
            if removed is None:
                raise WatchlistError("That player is no longer on the watchlist.")
            await interaction.edit_original_response(content=f"Removed **{removed.name}** from the watchlist.")
        except (WatchlistError, WatchlistResolutionError) as exc:
            await interaction.edit_original_response(content=compact_interaction_error("Couldn’t update the watchlist", exc))

    @watch_group.command(name="list", description="List your watched Premier League players")
    async def watch_list_command(interaction: discord.Interaction) -> None:
        if not await ensure_watchlist_user(interaction):
            return
        try:
            watched = await asyncio.to_thread(list_watchlist, watchlist_file(config))
            if not watched:
                content = "Your watchlist is empty. Add one with `/watch add player`."
            else:
                entries = "\n".join(
                    f"• **{entry.name}** — {entry.club} ({'/'.join(entry.positions) or 'position unavailable'})"
                    for entry in watched
                )
                content = f"**Your watchlist ({len(watched)})**\n{entries}"
            await interaction.response.send_message(content, allowed_mentions=discord.AllowedMentions.none())
        except WatchlistError as exc:
            await interaction.response.send_message(compact_interaction_error("Couldn’t read the watchlist", exc), ephemeral=True)

    command_tree.add_command(watch_group)

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
        caption = message.content.strip()
        attachment_metadata: dict | None = None
        try:
            attachment_input = await normalize_discord_attachment(message)
        except AttachmentIntakeError as exc:
            await send_chunks(message.channel, f"I couldn’t process that attachment: {exc}")
            return
        if attachment_input is not None:
            attachment_kind, attachment_metadata, attachment_text = attachment_input
            if attachment_kind in {"pdf", "text"} and not caption:
                source = attachment_metadata["attachment"]
                context_text = f"Attachment ({source['kind']}; {source['filename']}):\n{attachment_text}"
                remember_user_message(context_text, metadata=attachment_metadata)
                await send_chunks(
                    message.channel,
                    "I extracted that attachment and saved its text as conversation context. What would you like me to do with it?",
                )
                return
            if attachment_kind == "audio" and not caption:
                content = attachment_text
            else:
                display = attachment_metadata["attachment"]
                content = f"{caption}\n\nAttachment ({display['kind']}; {display['filename']}):\n{attachment_text}"
        else:
            content = caption
        if not content:
            return
        watchlist_intent = parse_watchlist_intent(caption or content)
        if watchlist_intent is not None:
            await handle_watchlist_dm(message, *watchlist_intent)
            return
        if content.casefold() in {"!help", "help"}:
            await send_chunks(
                message.channel,
                "Use `/ask` in my DM to open a local Codex task. "
                "Use `/analyze-waivers` for the full waiver shortlist and swap analysis. "
                "Use `/tasks` to see scheduled task IDs or `/task <id>` to run one now. "
                "Say “add [player] to my watchlist,” “remove [player] from my watchlist,” or “what’s on my watchlist?” "
                "You can also use `/watch add`, `/watch remove`, or `/watch list`. "
                "Text DMs are also accepted when Discord exposes them to the bot.",
            )
            return
        if content.casefold() == "!tasks":
            try:
                registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
                tasks = "\n".join(f"`{task.id}` — {task.name}" for task in registry.tasks)
                await send_chunks(message.channel, f"Registered tasks:\n{tasks}")
            except AutomationError as exc:
                await send_chunks(message.channel, f"I couldn’t read the task registry: {exc}")
            return
        await run_and_reply(message, content, user_metadata=attachment_metadata)

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
    client = build_client(config)
    client.run(config.discord_bot_token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
