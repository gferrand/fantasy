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
        "🧠 **Ask anything**\n`/ask` — research a player, fixture, or decision\n\n"
        "📬 **Reports**\n`/tasks` — see scheduled reports\n`/task <id>` — run one now\n\n"
        "👀 **Watchlist**\n`/watch add`, `/watch remove`, `/watch list`\n"
        "You can also message me normally when Discord supports bot DMs."
    )


def watchlist_empty() -> str:
    return "👀 **Your watchlist is empty**\nAdd a player with `/watch add player`."


def watchlist_card(entries: Iterable[object]) -> str:
    watched = list(entries)
    lines = []
    for entry in watched:
        name = str(getattr(entry, "name"))
        club = str(getattr(entry, "club"))
        positions = "/".join(getattr(entry, "positions")) or "position unavailable"
        lines.append(f"• **{name}** · {club} · {positions}")
    return f"👀 **Your watchlist · {len(watched)} players**\n\n" + "\n".join(lines)


def watchlist_change(action: str, entry: object) -> str:
    name = str(getattr(entry, "name"))
    club = str(getattr(entry, "club"))
    positions = "/".join(getattr(entry, "positions")) or "position unavailable"
    if action == "added":
        return f"✅ **Added to watchlist**\n**{name}** · {club} · {positions}"
    if action == "already_watching":
        return f"👀 **Already on your watchlist**\n**{name}** · {club} · {positions}"
    if action == "removed":
        return f"🗑️ **Removed from watchlist**\n**{name}**"
    raise ValueError(f"Unknown watchlist action: {action}")


def attachment_processing() -> str:
    return "📎 **Reading your attachment…**"


def attachment_ready() -> str:
    return "✅ **Attachment saved to context**\nWhat would you like me to do with it?"


def private_advisor_only() -> str:
    return "🔒 **Private advisor**\nThis bot is only available to its configured account."


def response_limit_notice() -> str:
    return "⚠️ **This report is too long for one Discord command response**\nRun the same report locally to read the full result."
