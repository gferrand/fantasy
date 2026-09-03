"""Fixture-aware, private lineup alerts for the owner's Sleeper roster."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .automation import AppConfig, AutomationError, EXPECTED_MANAGER_ID, WebResult
from .gameweek import GameweekContext, load_gameweek_prepare_context


ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"
CLUB_ABBRS = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "AFC Bournemouth": "BOU", "Bournemouth": "BOU",
    "Brentford": "BRE", "Brighton & Hove Albion": "BHA", "Brighton": "BHA", "Chelsea": "CHE",
    "Crystal Palace": "CRY", "Everton": "EVE", "Fulham": "FUL", "Hull City": "HUL",
    "Ipswich Town": "IPS", "Leeds United": "LEE", "Liverpool": "LIV", "Manchester City": "MCI",
    "Manchester United": "MUN", "Newcastle United": "NEW", "Nottingham Forest": "NFO",
    "Sunderland": "SUN", "Tottenham Hotspur": "TOT", "Coventry City": "COV",
}


@dataclass(frozen=True)
class LineupFixture:
    event_id: str
    kickoff: datetime
    home: str
    away: str
    players: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class FixtureAlertWindow:
    """One scheduled pre-kickoff check for a published EPL fixture."""

    event_id: str
    kickoff: datetime
    alert_at: datetime


class EplFixtureClient:
    """Small read-only client for the public EPL scoreboard schedule."""

    def get_schedule(self, start: datetime, end: datetime) -> object:
        query = urlencode({"dates": f"{start:%Y%m%d}-{end:%Y%m%d}", "limit": "1000"})
        # ESPN's public scoreboard currently accepts its lightweight API clients
        # but rejects browser-style and product-branded User-Agent strings.
        request = Request(f"{ESPN_SCOREBOARD_URL}?{query}", headers={"User-Agent": "curl/8.7.1"})
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except Exception as exc:  # pragma: no cover - network behavior is exercised live
            raise AutomationError("Could not load the current Premier League fixture schedule") from exc


def lineup_alert_state_file(config: AppConfig) -> Path:
    return config.repo_root / "data" / "automation" / "lineup_alerts.json"


def lineup_fixture_cache_file(config: AppConfig) -> Path:
    """Return the private persisted copy of the published fixture board."""

    return config.repo_root / "data" / "automation" / "lineup_fixtures.json"


def fixture_season_window(now: datetime) -> tuple[datetime, datetime]:
    """Return the complete published EPL season window containing ``now``."""

    current = now.astimezone(timezone.utc)
    season_start_year = current.year if current.month >= 7 else current.year - 1
    return (
        datetime(season_start_year, 8, 1, tzinfo=timezone.utc),
        datetime(season_start_year + 1, 6, 15, tzinfo=timezone.utc),
    )


def load_fixture_schedule(
    config: AppConfig,
    *,
    now: datetime,
    fixture_client: EplFixtureClient | None = None,
) -> object:
    """Return the locally persisted published season, downloading it only if absent."""

    cache_path = lineup_fixture_cache_file(config)
    current = now.astimezone(timezone.utc)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            schedule = cached.get("schedule") if isinstance(cached, Mapping) else None
            if _is_complete_fixture_schedule(schedule):
                return schedule
        except (OSError, json.JSONDecodeError):
            # A partial cache must never block a fresh public schedule fetch.
            pass
    season_start, season_end = fixture_season_window(current)
    schedule = (fixture_client or EplFixtureClient()).get_schedule(season_start, season_end)
    if not _is_complete_fixture_schedule(schedule):
        raise AutomationError("Premier League fixture schedule did not return a complete valid season")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"retrieved_at": current.isoformat(), "schedule": schedule}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(cache_path)
    return schedule


def load_persisted_fixture_schedule(config: AppConfig) -> object:
    """Read the complete local season schedule without any network refresh.

    Forecasting uses the same deliberately static schedule as the lineup-alert
    service. A trade request must not quietly replace it with a new download or
    make a fixture prediction from a partial cache.
    """

    cache_path = lineup_fixture_cache_file(config)
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutomationError(
            "The local Premier League fixture schedule is not initialized; restore the downloaded season calendar first."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AutomationError("The local Premier League fixture schedule is unreadable") from exc
    schedule = cached.get("schedule") if isinstance(cached, Mapping) else None
    if not _is_complete_fixture_schedule(schedule):
        raise AutomationError("The local Premier League fixture schedule is incomplete or invalid")
    return schedule


def _load_sent(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _quarantine_corrupt_state(path)
        return set()
    except OSError as exc:
        raise AutomationError("Lineup alert state is unreadable") from exc
    sent = payload.get("sent") if isinstance(payload, Mapping) else None
    if not isinstance(sent, list):
        _quarantine_corrupt_state(path)
        return set()
    return {str(value) for value in sent if str(value).strip()}


def _quarantine_corrupt_state(path: Path) -> None:
    """Preserve a bad state file while allowing a pending alert to be delivered."""

    backup = path.with_suffix(path.suffix + ".corrupt")
    try:
        path.replace(backup)
    except OSError as exc:
        raise AutomationError("Lineup alert state is unreadable") from exc


def _mark_sent(path: Path, event_id: str) -> None:
    prior = _load_sent(path)
    prior.add(event_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"sent": sorted(prior)}, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def _parse_kickoff(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _is_complete_fixture_schedule(schedule: object) -> bool:
    """Reject partial or malformed season downloads instead of silently missing matches."""

    if not isinstance(schedule, Mapping) or not isinstance(schedule.get("events"), list):
        return False
    events = schedule["events"]
    # A 20-club Premier League season has 380 fixtures. The all-or-nothing
    # check prevents an incomplete scoreboard response becoming the calendar.
    if len(events) != 380:
        return False
    event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, Mapping):
            return False
        event_id = str(event.get("id") or "").strip()
        if not event_id or event_id in event_ids or _parse_kickoff(event.get("date")) is None:
            return False
        event_ids.add(event_id)
        competitions = event.get("competitions")
        competition = competitions[0] if isinstance(competitions, list) and competitions and isinstance(competitions[0], Mapping) else None
        competitors = competition.get("competitors") if isinstance(competition, Mapping) else None
        if not isinstance(competitors, list) or len(competitors) != 2:
            return False
        sides = {str(item.get("homeAway") or "") for item in competitors if isinstance(item, Mapping)}
        names = {
            str(item.get("team", {}).get("displayName") or "").strip()
            for item in competitors
            if isinstance(item, Mapping) and isinstance(item.get("team"), Mapping)
        }
        if sides != {"home", "away"} or len(names) != 2 or any(name not in CLUB_ABBRS for name in names):
            return False
    return True


def roster_fixtures(context: GameweekContext, schedule: object) -> tuple[LineupFixture, ...]:
    """Return scheduled fixtures containing one or more current roster players."""

    if not isinstance(schedule, Mapping) or not isinstance(schedule.get("events"), list):
        raise AutomationError("Premier League fixture schedule did not return an events array")
    team = context.payload.get("your_team")
    players = team.get("players") if isinstance(team, Mapping) else []
    players = [item for item in players if isinstance(item, Mapping)] if isinstance(players, list) else []
    results: list[LineupFixture] = []
    for event in schedule["events"]:
        if not isinstance(event, Mapping):
            continue
        event_id = str(event.get("id") or "").strip()
        kickoff = _parse_kickoff(event.get("date"))
        competitions = event.get("competitions")
        competition = competitions[0] if isinstance(competitions, list) and competitions and isinstance(competitions[0], Mapping) else {}
        competitors = competition.get("competitors") if isinstance(competition, Mapping) else []
        home = away = None
        if isinstance(competitors, list):
            for competitor in competitors:
                if not isinstance(competitor, Mapping) or not isinstance(competitor.get("team"), Mapping):
                    continue
                name = str(competitor["team"].get("displayName") or "").strip()
                if competitor.get("homeAway") == "home":
                    home = name
                elif competitor.get("homeAway") == "away":
                    away = name
        if not event_id or kickoff is None or not home or not away:
            continue
        clubs = {CLUB_ABBRS.get(home), CLUB_ABBRS.get(away)}
        relevant = tuple(dict(player) for player in players if str(player.get("club") or "").upper() in clubs)
        if relevant:
            results.append(LineupFixture(event_id, kickoff, home, away, relevant))
    return tuple(sorted(results, key=lambda fixture: fixture.kickoff))


def due_fixtures(
    fixtures: Iterable[LineupFixture], *, now: datetime, lead_minutes: int, sent: set[str]
) -> tuple[LineupFixture, ...]:
    """Return unsent fixtures whose decision window is open and kickoff has not passed."""

    current = now.astimezone(timezone.utc)
    lead = timedelta(minutes=lead_minutes)
    return tuple(
        fixture for fixture in fixtures
        if fixture.event_id not in sent and fixture.kickoff - lead <= current < fixture.kickoff
    )


def fixture_alert_windows(
    schedule: object,
    *,
    now: datetime,
    lead_minutes: int,
    checked_event_ids: set[str] | None = None,
) -> tuple[FixtureAlertWindow, ...]:
    """Calculate the exact future checks from the already-downloaded schedule."""

    if not isinstance(schedule, Mapping) or not isinstance(schedule.get("events"), list):
        raise AutomationError("Premier League fixture schedule did not return an events array")
    current = now.astimezone(timezone.utc)
    checked = checked_event_ids or set()
    lead = timedelta(minutes=lead_minutes)
    windows = []
    for event in schedule["events"]:
        if not isinstance(event, Mapping):
            continue
        event_id = str(event.get("id") or "").strip()
        kickoff = _parse_kickoff(event.get("date"))
        if not event_id or event_id in checked or kickoff is None or kickoff <= current:
            continue
        windows.append(FixtureAlertWindow(event_id, kickoff, max(kickoff - lead, current)))
    return tuple(sorted(windows, key=lambda window: (window.alert_at, window.event_id)))


def lineup_alert_context(context: GameweekContext, fixtures: Iterable[LineupFixture]) -> str:
    """Serialize one kickoff window, which can contain several simultaneous matches."""

    fixture_list = tuple(fixtures)
    starters = context.payload.get("your_team", {}).get("current_starters", [])
    return json.dumps(
        {
            "source": "live Sleeper roster plus current Premier League schedule",
            "gameweek": context.gameweek,
            "fixtures": [
                {
                    "event_id": fixture.event_id,
                    "kickoff_utc": fixture.kickoff.isoformat(),
                    "home": fixture.home,
                    "away": fixture.away,
                    "relevant_roster_players": fixture.players,
                }
                for fixture in fixture_list
            ],
            "current_sleeper_starter_ids": starters,
            "starting_slots": context.payload.get("starting_slots", []),
            "instruction": "This is a read-only alert. Do not make a Sleeper lineup or roster change.",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def fallback_lineup_alert(context: GameweekContext, fixtures: Iterable[LineupFixture]) -> str:
    """Build a factual alert when optional research cannot complete in time."""

    starters = {
        str(player_id)
        for player_id in context.payload.get("your_team", {}).get("current_starters", [])
    }
    lines = ["⏰ **Lineup check**", "Live roster + fixture match detected."]
    for fixture in fixtures:
        players = ", ".join(
            f"{player.get('name', 'Unknown player')} ({'currently starting' if str(player.get('player_id')) in starters else 'not currently starting'})"
            for player in fixture.players
        )
        lines.append(f"{fixture.home} vs {fixture.away} — {fixture.kickoff:%Y-%m-%d %H:%M UTC}")
        lines.append(f"Your players: {players}")
    lines.append("The live research briefing was unavailable; confirm manually in Sleeper before kickoff.")
    return "\n".join(lines)


def guardian_prompt(text: str) -> str:
    """Make the manual acknowledgement route obvious without implying a Sleeper action."""

    return text.rstrip() + "\n\n✅ Review your lineup manually, then reply `done` or use `/guardian done`."


def run_lineup_alerts(
    config: AppConfig,
    *,
    now: datetime | None = None,
    fixture_client: EplFixtureClient | None = None,
    prepare_loader: Callable[..., GameweekContext] = load_gameweek_prepare_context,
    analyst: Callable[..., WebResult] | None = None,
    transport: Any | None = None,
    schedule: object | None = None,
) -> int:
    """Send each fixture's private check once, inside its pre-kickoff window."""

    from .automation import run_lineup_alert_web_briefing
    from .discord_transport import DiscordTransport

    current = now or datetime.now(timezone.utc)
    current = current.astimezone(timezone.utc)
    context = prepare_loader(manager_id=EXPECTED_MANAGER_ID)
    fixture_schedule = schedule if schedule is not None else load_fixture_schedule(
        config,
        now=current,
        fixture_client=fixture_client,
    )
    state_path = lineup_alert_state_file(config)
    pending = due_fixtures(
        roster_fixtures(context, fixture_schedule),
        now=current,
        lead_minutes=config.lineup_alert_lead_minutes,
        sent=_load_sent(state_path),
    )
    if not pending:
        return 0
    config.require_discord()
    sender = transport or DiscordTransport(config.discord_bot_token or "")
    briefing = analyst or run_lineup_alert_web_briefing
    delivered = 0
    windows: dict[datetime, list[LineupFixture]] = {}
    for fixture in pending:
        windows.setdefault(fixture.kickoff, []).append(fixture)
    for fixtures in windows.values():
        try:
            result = briefing(config, live_context=lineup_alert_context(context, fixtures))
            text = result.text
        except Exception:
            # Research is valuable but must never suppress the time-sensitive
            # fixture alert when the roster and kickoff are already known.
            text = fallback_lineup_alert(context, fixtures)
        sender.send_dm(config.discord_allowed_user_id or "", guardian_prompt(text))
        for fixture in fixtures:
            _mark_sent(state_path, fixture.event_id)
        from .deadline_guardian import record_initial_alerts

        record_initial_alerts(config, fixtures, now=current)
        delivered += 1
    return delivered


def run_deadline_guardian(
    config: AppConfig,
    *,
    now: datetime | None = None,
    prepare_loader: Callable[..., GameweekContext] = load_gameweek_prepare_context,
    analyst: Callable[..., WebResult] | None = None,
    transport: Any | None = None,
    schedule: object,
) -> int:
    """Escalate once near kickoff when the owner has not acknowledged an alert."""

    from .automation import run_lineup_alert_web_briefing
    from .deadline_guardian import final_reminder_events, mark_final_reminded
    from .discord_transport import DiscordTransport

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    due = final_reminder_events(config, now=current, lead_minutes=config.deadline_guardian_final_lead_minutes)
    if not due:
        return 0
    context = prepare_loader(manager_id=EXPECTED_MANAGER_ID)
    by_id = {fixture.event_id: fixture for fixture in roster_fixtures(context, schedule)}
    relevant = [by_id[event.event_id] for event in due if event.event_id in by_id]
    # A player may have been dropped since the first alert. Mark that stale
    # item complete rather than sending an irrelevant escalation.
    stale_ids = [event.event_id for event in due if event.event_id not in by_id]
    if stale_ids:
        mark_final_reminded(config, stale_ids, now=current)
    if not relevant:
        return 0
    config.require_discord()
    sender = transport or DiscordTransport(config.discord_bot_token or "")
    briefing = analyst or run_lineup_alert_web_briefing
    groups: dict[datetime, list[LineupFixture]] = {}
    for fixture in relevant:
        groups.setdefault(fixture.kickoff, []).append(fixture)
    delivered = 0
    for fixtures in groups.values():
        try:
            result = briefing(config, live_context=lineup_alert_context(context, fixtures))
            detail = result.text
        except Exception:
            detail = fallback_lineup_alert(context, fixtures)
        message = (
            "⚠️ **Final lineup check**\n"
            "You have not acknowledged the earlier alert. Recheck manually before kickoff.\n\n"
            + guardian_prompt(detail)
        )
        sender.send_dm(config.discord_allowed_user_id or "", message)
        mark_final_reminded(config, (fixture.event_id for fixture in fixtures), now=current)
        delivered += 1
    return delivered
