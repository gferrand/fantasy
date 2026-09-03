"""Durable acknowledgement and final-check state for private lineup alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Iterable, Mapping

from .automation import AppConfig, AutomationError


@dataclass(frozen=True)
class GuardianEvent:
    event_id: str
    kickoff: datetime
    home: str
    away: str
    alerted_at: datetime
    acknowledged_at: datetime | None
    final_reminded_at: datetime | None


def guardian_state_file(config: AppConfig) -> Path:
    return config.repo_root / "data" / "automation" / "deadline_guardian.json"


def parse_guardian_intent(text: str) -> str | None:
    """Recognize only unambiguous acknowledgement/status text in a private DM."""

    normalized = " ".join(text.casefold().strip().split())
    if normalized in {"done", "lineup done", "guardian done", "/guardian done", "acknowledged"}:
        return "done"
    if normalized in {"guardian status", "/guardian status"}:
        return "status"
    return None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _load(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutomationError("Deadline Guardian state is unreadable") from exc
    events = raw.get("events") if isinstance(raw, Mapping) else None
    if not isinstance(events, Mapping):
        raise AutomationError("Deadline Guardian state is malformed")
    return {str(key): dict(value) for key, value in events.items() if isinstance(value, Mapping)}


def _write(path: Path, events: Mapping[str, Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"events": events}, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def _event(event_id: str, value: Mapping[str, object]) -> GuardianEvent | None:
    kickoff = _parse_time(value.get("kickoff"))
    alerted_at = _parse_time(value.get("alerted_at"))
    home = str(value.get("home") or "").strip()
    away = str(value.get("away") or "").strip()
    if kickoff is None or alerted_at is None or not home or not away:
        return None
    return GuardianEvent(
        event_id=event_id,
        kickoff=kickoff,
        home=home,
        away=away,
        alerted_at=alerted_at,
        acknowledged_at=_parse_time(value.get("acknowledged_at")),
        final_reminded_at=_parse_time(value.get("final_reminded_at")),
    )


def active_events(config: AppConfig, *, now: datetime) -> tuple[GuardianEvent, ...]:
    """Return still-relevant Guardian items from the private durable state."""

    current = now.astimezone(timezone.utc)
    events = _load(guardian_state_file(config))
    parsed = [_event(event_id, value) for event_id, value in events.items()]
    return tuple(sorted((item for item in parsed if item is not None and item.kickoff > current), key=lambda item: item.kickoff))


def record_initial_alerts(config: AppConfig, fixtures: Iterable[object], *, now: datetime) -> None:
    """Persist an acknowledged-or-pending Guardian item after a successful DM."""

    path = guardian_state_file(config)
    events = _load(path)
    current = now.astimezone(timezone.utc).isoformat()
    for fixture in fixtures:
        event_id = str(getattr(fixture, "event_id", "")).strip()
        kickoff = getattr(fixture, "kickoff", None)
        home = str(getattr(fixture, "home", "")).strip()
        away = str(getattr(fixture, "away", "")).strip()
        if not event_id or not isinstance(kickoff, datetime) or not home or not away:
            raise AutomationError("Could not record an invalid Deadline Guardian fixture")
        existing = events.get(event_id, {})
        events[event_id] = {
            "kickoff": kickoff.astimezone(timezone.utc).isoformat(),
            "home": home,
            "away": away,
            "alerted_at": str(existing.get("alerted_at") or current),
            "acknowledged_at": existing.get("acknowledged_at"),
            "final_reminded_at": existing.get("final_reminded_at"),
        }
    _write(path, events)


def acknowledge_active_events(config: AppConfig, *, now: datetime) -> tuple[GuardianEvent, ...]:
    """Acknowledge every currently open fixture alert in one explicit user action."""

    path = guardian_state_file(config)
    events = _load(path)
    current = now.astimezone(timezone.utc)
    acknowledged: list[GuardianEvent] = []
    for event_id, value in events.items():
        event = _event(event_id, value)
        if event is None or event.kickoff <= current or event.acknowledged_at is not None:
            continue
        value["acknowledged_at"] = current.isoformat()
        acknowledged.append(_event(event_id, value) or event)
    _write(path, events)
    return tuple(sorted(acknowledged, key=lambda item: item.kickoff))


def final_reminder_events(
    config: AppConfig, *, now: datetime, lead_minutes: int
) -> tuple[GuardianEvent, ...]:
    """Return unacknowledged fixtures in their single final reminder window."""

    current = now.astimezone(timezone.utc)
    lead = timedelta(minutes=lead_minutes)
    return tuple(
        event for event in active_events(config, now=current)
        if event.acknowledged_at is None
        and event.final_reminded_at is None
        and event.kickoff - lead <= current < event.kickoff
    )


def final_reminder_windows(
    config: AppConfig, *, now: datetime, lead_minutes: int
) -> tuple[datetime, ...]:
    """Return exact future wake times for unacknowledged Guardian items."""

    current = now.astimezone(timezone.utc)
    lead = timedelta(minutes=lead_minutes)
    return tuple(sorted({max(event.kickoff - lead, current) for event in active_events(config, now=current)
                         if event.acknowledged_at is None and event.final_reminded_at is None}))


def mark_final_reminded(config: AppConfig, event_ids: Iterable[str], *, now: datetime) -> None:
    path = guardian_state_file(config)
    events = _load(path)
    timestamp = now.astimezone(timezone.utc).isoformat()
    for event_id in event_ids:
        value = events.get(str(event_id))
        if isinstance(value, dict):
            value["final_reminded_at"] = timestamp
    _write(path, events)
