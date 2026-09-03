"""Small, consistent message layouts for the private Discord advisor."""

from __future__ import annotations

from collections.abc import Iterable


def error_card(title: str, detail: str | None = None) -> str:
    """Render a compact, human-readable failure without platform jargon."""

    message = f"⚠️ **{title}**"
    return f"{message}\n{detail.strip()}" if detail and detail.strip() else message


def working_card() -> str:
    return "⏳ **Checking that now**\nI’ll post a read-only answer here when it’s ready."


def advisor_header() -> str:
    return "🧠 **Fantasy Advisor**\n📱 *Quick, read-only guidance for Los Blancos*"


def web_briefing_header() -> str:
    return "🌐 **Fantasy Briefing**\n📱 *Focused live-web research · read-only*"


def waiver_header() -> str:
    return "🏟️ **Los Blancos — Waiver Wire**\n📱 *Phone-friendly view · manual review only*"


def scheduled_header(task_name: str, timestamp: str) -> str:
    return f"📬 **{task_name}**\n🕒 *{timestamp}*"


def scheduled_failure(task_name: str, detail: str) -> str:
    return error_card(f"{task_name} didn’t run", detail)


def task_menu(tasks: Iterable[object]) -> str:
    rows = []
    for task in tasks:
        task_id = str(getattr(task, "id"))
        name = str(getattr(task, "name"))
        rows.append(f"• **{name}**\n  Run now: `/task {task_id}`")
    return "📚 **Your scheduled reports**\n\n" + "\n".join(rows)


def help_menu() -> str:
    return (
        "🧭 **Fantasy Advisor guide**\n\n"
        "🏟️ **Waivers**\n`/analyze-waivers` — pickups and manual-review swaps\n\n"
        "🗓️ **Gameweek**\n`/gameweek prepare` — next lineup, fixtures, and key opponents\n"
        "`/gameweek recap` — last completed gameweek and watchlist signals\n\n"
        "🧠 **Ask anything**\n`/ask` — research a player, fixture, or decision\n\n"
        "📬 **Reports**\n`/tasks` — see scheduled reports\n`/task <id>` — run one now\n\n"
        "🛡️ **Deadline Guardian**\n`/guardian done` — acknowledge current lineup alerts\n"
        "`/guardian status` — view open alerts\n\n"
        "👀 **Watchlist**\n`/watch add`, `/watch remove`, `/watch list`, `/watch stats`\n"
        "`/watch outlook` — current news and expert view\n"
        "`/watch recommend` — manual roster-fit ideas\n"
        "Refresh player references: `/player_catalog update`\n"
        "You can also message me normally when Discord supports bot DMs."
    )


def player_catalog_updated(result: object) -> str:
    """Render the result of a manual local player catalog refresh."""

    count = int(getattr(result, "player_count"))
    refreshed_at = str(getattr(result, "refreshed_at"))
    return (
        "📚 **Player catalog updated**\n"
        f"{count:,} Sleeper EPL player references saved locally.\n"
        f"Updated: {refreshed_at}"
    )


def watchlist_empty() -> str:
    return "👀 **Your watchlist is empty**\nAdd a player with `/watch add player`."


def guardian_acknowledged(events: Iterable[object]) -> str:
    items = list(events)
    if not items:
        return "✅ **Deadline Guardian**\nThere are no open lineup alerts to acknowledge."
    fixtures = ", ".join(f"{getattr(item, 'home')} vs {getattr(item, 'away')}" for item in items)
    return (
        f"✅ **Lineup alert acknowledged**\n{fixtures}\n"
        "No final reminder will be sent for these fixtures. Check `/guardian status` anytime."
    )


def guardian_status(events: Iterable[object]) -> str:
    items = list(events)
    if not items:
        return "🛡️ **Deadline Guardian**\nNo upcoming lineup alerts are currently open."
    lines = ["🛡️ **Deadline Guardian**"]
    for item in items:
        state = "acknowledged" if getattr(item, "acknowledged_at") else "awaiting your acknowledgement"
        lines.append(f"• **{getattr(item, 'home')} vs {getattr(item, 'away')}** · {state}")
    return "\n".join(lines)


def watchlist_card(entries: Iterable[object]) -> str:
    watched = list(entries)
    lines = []
    for entry in watched:
        name = str(getattr(entry, "name"))
        club = str(getattr(entry, "club")) or "no current club"
        positions = "/".join(getattr(entry, "positions")) or "position unavailable"
        lines.append(f"• **{name}** · {club} · {positions}")
    return f"👀 **Your watchlist · {len(watched)} players**\n\n" + "\n".join(lines)


def watchlist_change(action: str, entry: object) -> str:
    name = str(getattr(entry, "name"))
    club = str(getattr(entry, "club")) or "no current club"
    positions = "/".join(getattr(entry, "positions")) or "position unavailable"
    if action == "added":
        return f"✅ **Added to watchlist**\n**{name}** · {club} · {positions}"
    if action == "already_watching":
        return f"👀 **Already on your watchlist**\n**{name}** · {club} · {positions}"
    if action == "removed":
        return f"🗑️ **Removed from watchlist**\n**{name}**"
    raise ValueError(f"Unknown watchlist action: {action}")


def _stat_value(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def watchlist_stats_card(report: object) -> str:
    """Render the just-fetched current Sleeper totals for every watched player."""

    season = str(getattr(report, "season"))
    week = getattr(report, "week")
    retrieved_at = str(getattr(report, "retrieved_at"))
    entries = list(getattr(report, "entries"))
    window = f"Sleeper EPL · {season} regular season"
    if week is not None:
        window += f" · GW{week}"
    lines = [f"📊 **Watchlist stats · {len(entries)} players**", f"*{window} · fetched {retrieved_at}*"]
    for entry in entries:
        player = getattr(entry, "player")
        club = str(getattr(player, "club")) or "no current club"
        positions = "/".join(getattr(player, "positions")) or "position unavailable"
        lines.extend(("", f"• **{getattr(player, 'name')}** · {club} · {positions}"))
        if not getattr(entry, "found"):
            lines.append("  No current regular-season Sleeper stats returned.")
            continue
        summary = []
        for label, field in (("Pts", "points"), ("GP", "games"), ("GS", "starts"), ("Min", "minutes")):
            value = getattr(entry, field)
            if value is not None:
                summary.append(f"{label} {_stat_value(value)}")
        lines.append("  " + " · ".join(summary or ["No scored stats returned."]))
        details = []
        for label, field in (("G", "goals"), ("A", "assists"), ("CS", "clean_sheets"), ("SV", "saves")):
            value = getattr(entry, field)
            if value is not None:
                details.append(f"{label} {_stat_value(value)}")
        if details:
            lines.append("  " + " · ".join(details))
        injury_status = getattr(entry, "injury_status")
        if injury_status:
            lines.append(f"  Injury status: {injury_status}")
    return "\n".join(lines)


def attachment_processing() -> str:
    return "📎 **Reading your attachment…**"


def attachment_ready() -> str:
    return "✅ **Attachment saved to context**\nWhat would you like me to do with it?"


def private_advisor_only() -> str:
    return "🔒 **Private advisor**\nThis bot is only available to its configured account."


def response_limit_notice() -> str:
    return "⚠️ **This report is too long for one Discord command response**\nRun the same report locally to read the full result."
