"""Local, network-free application health state and probe CLI."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
from typing import Callable, Iterable


HEALTH_COMPONENTS = ("discord", "scheduler")
HEARTBEAT_INTERVAL_SECONDS = 60.0
DEFAULT_MAX_AGE_SECONDS = 180.0
MAX_BUSY_LEASE_SECONDS = 3_600.0
MAX_HEALTH_FILE_BYTES = 16_384
SCHEMA_VERSION = 1
ROOT = Path(os.environ.get("FANTASY_REPO_ROOT", Path(__file__).resolve().parents[2]))


@dataclass(frozen=True)
class HealthResult:
    component: str
    healthy: bool
    reason: str
    age_seconds: float | None = None
    state: str | None = None
    busy_until: float | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "component": self.component,
            "status": "healthy" if self.healthy else "unhealthy",
            "reason": self.reason,
        }
        if self.age_seconds is not None:
            result["age_seconds"] = round(self.age_seconds, 3)
        if self.state is not None:
            result["state"] = self.state
        if self.busy_until is not None:
            result["busy_until"] = self.busy_until
        return result


def health_state_file(repo_root: Path, component: str) -> Path:
    if component not in HEALTH_COMPONENTS:
        raise ValueError(f"Unsupported health component: {component}")
    return repo_root / "data" / "automation" / "health" / f"{component}.json"


def write_health_state(
    repo_root: Path,
    component: str,
    *,
    healthy: bool = True,
    unhealthy_components: Iterable[str] = (),
    now: float | None = None,
    busy_until: float | None = None,
) -> Path:
    """Atomically record local application activity without probing a dependency."""

    timestamp = time.time() if now is None else now
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
        raise ValueError("Health timestamp must be finite")
    timestamp = float(timestamp)
    if busy_until is not None:
        if (
            isinstance(busy_until, bool)
            or not isinstance(busy_until, (int, float))
            or not math.isfinite(busy_until)
        ):
            raise ValueError("Busy lease deadline must be finite")
        busy_until = float(busy_until)
        lease_seconds = busy_until - timestamp
        if lease_seconds <= 0 or lease_seconds > MAX_BUSY_LEASE_SECONDS:
            raise ValueError("Busy lease must end within 3600 seconds after updated_at")
    failures = sorted({str(item) for item in unhealthy_components if str(item)})
    if healthy and failures:
        raise ValueError("Healthy state cannot include unhealthy components")
    path = health_state_file(repo_root, component)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "component": component,
        "status": "healthy" if healthy else "unhealthy",
        "state": "busy" if busy_until is not None else "idle",
        "updated_at": timestamp,
        "busy_until": busy_until,
        "unhealthy_components": failures,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


async def maintain_ready_heartbeat(
    repo_root: Path,
    component: str,
    *,
    is_ready: Callable[[], bool],
    is_closed: Callable[[], bool],
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """Refresh a heartbeat only while a long-lived client reports ready."""

    while not is_closed():
        if is_ready():
            write_health_state(repo_root, component)
        await asyncio.sleep(interval_seconds)


def check_health(
    repo_root: Path,
    component: str,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> HealthResult:
    """Validate a component heartbeat and its last reported application status."""

    if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise ValueError("Maximum heartbeat age must be positive and finite")
    current = time.time() if now is None else now
    if isinstance(current, bool) or not isinstance(current, (int, float)) or not math.isfinite(current):
        raise ValueError("Current health-check time must be finite")
    current = float(current)
    path = health_state_file(repo_root, component)
    try:
        size = path.stat().st_size
        if size > MAX_HEALTH_FILE_BYTES:
            return HealthResult(component, False, "health_state_too_large")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return HealthResult(component, False, "health_state_missing")
    except (OSError, UnicodeError, json.JSONDecodeError):
        return HealthResult(component, False, "health_state_unreadable")
    if not isinstance(payload, dict):
        return HealthResult(component, False, "health_state_invalid")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("component") != component:
        return HealthResult(component, False, "health_state_invalid")
    status = payload.get("status")
    state = payload.get("state")
    failures = payload.get("unhealthy_components")
    if status not in {"healthy", "unhealthy"} or state not in {"idle", "busy"}:
        return HealthResult(component, False, "health_state_invalid")
    if (
        not isinstance(failures, list)
        or any(not isinstance(item, str) or not item for item in failures)
        or len(failures) != len(set(failures))
        or (status == "healthy" and failures)
    ):
        return HealthResult(component, False, "health_state_invalid")
    updated_at = payload.get("updated_at")
    if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)):
        return HealthResult(component, False, "health_timestamp_invalid")
    updated_at = float(updated_at)
    if not math.isfinite(updated_at):
        return HealthResult(component, False, "health_timestamp_invalid")
    age = current - updated_at
    if age < 0:
        return HealthResult(component, False, "health_timestamp_in_future", age)
    busy_until = payload.get("busy_until")
    if state == "busy":
        if (
            isinstance(busy_until, bool)
            or not isinstance(busy_until, (int, float))
            or not math.isfinite(busy_until)
        ):
            return HealthResult(component, False, "busy_lease_invalid", age, state)
        busy_until = float(busy_until)
        lease_seconds = busy_until - updated_at
        if lease_seconds <= 0 or lease_seconds > MAX_BUSY_LEASE_SECONDS:
            return HealthResult(component, False, "busy_lease_invalid", age, state, busy_until)
        if current > busy_until:
            return HealthResult(component, False, "busy_lease_expired", age, state, busy_until)
    elif busy_until is not None:
        return HealthResult(component, False, "busy_lease_invalid", age, state)
    if status != "healthy":
        return HealthResult(component, False, "component_reported_unhealthy", age, state, busy_until)
    if state == "busy":
        return HealthResult(component, True, "busy_lease_valid", age, state, busy_until)
    if age > max_age_seconds:
        return HealthResult(component, False, "health_state_stale", age, state)
    return HealthResult(component, True, "heartbeat_fresh", age, state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Fantasy application health without network access")
    parser.add_argument("--component", required=True, choices=HEALTH_COMPONENTS)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--max-age-seconds", type=float, default=DEFAULT_MAX_AGE_SECONDS)
    args = parser.parse_args(argv)
    try:
        result = check_health(
            args.repo_root,
            args.component,
            max_age_seconds=args.max_age_seconds,
        )
    except ValueError as exc:
        print(json.dumps({"component": args.component, "status": "unhealthy", "reason": str(exc)}))
        return 2
    payload = result.as_dict()
    payload["checked_at"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if result.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
