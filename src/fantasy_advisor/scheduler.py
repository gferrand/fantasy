"""Small container-native scheduler for the registered Fantasy tasks."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .automation import AppConfig, AutomationError, TaskSpec, load_registry, run_scheduled_task
from .lineup_alerts import fixture_alert_windows, load_fixture_schedule, run_lineup_alerts

LOGGER = logging.getLogger(__name__)


def _is_due(task: TaskSpec, now: datetime) -> bool:
    if task.schedule_type == "hourly":
        return task.minute_past_hour == now.minute
    if task.schedule_type == "daily" and task.run_at:
        hour, minute = (int(part) for part in task.run_at.split(":", 1))
        return now.hour == hour and now.minute == minute
    return False


def _next_task_time(tasks: tuple[TaskSpec, ...], now: datetime) -> datetime:
    """Return the next wall-clock task run without polling every minute."""

    candidates: list[datetime] = []
    for task in tasks:
        if task.schedule_type == "hourly" and task.minute_past_hour is not None:
            candidate = now.replace(minute=task.minute_past_hour, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(hours=1)
            candidates.append(candidate)
        elif task.schedule_type == "daily" and task.run_at:
            hour, minute = (int(part) for part in task.run_at.split(":", 1))
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            candidates.append(candidate)
    return min(candidates) if candidates else now + timedelta(hours=12)


def _sleep_until(now: datetime, *targets: datetime | None) -> float:
    """Sleep exactly to the next known report, fixture check, or retry."""

    future = [target for target in targets if target is not None and target > now]
    if not future:
        return 1.0
    return max(1.0, (min(future) - now).total_seconds())


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = AppConfig.from_environment()
    registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
    zone = ZoneInfo(registry.timezone)
    completed_minutes: set[tuple[str, str]] = set()
    fixture_schedule = None
    fixture_retry_at: datetime | None = None
    checked_fixture_ids: set[str] = set()
    LOGGER.info("Fantasy container scheduler started for %s", registry.timezone)
    while True:
        now = datetime.now(zone)
        minute_key = now.isoformat()
        for task in registry.tasks:
            key = (task.id, minute_key)
            if key in completed_minutes or not _is_due(task, now):
                continue
            completed_minutes.add(key)
            try:
                LOGGER.info("Starting scheduled task %s", task.id)
                run_scheduled_task(config, task.id)
                LOGGER.info("Completed scheduled task %s", task.id)
            except AutomationError:
                LOGGER.exception("Scheduled task %s failed", task.id)
        if fixture_schedule is None and (fixture_retry_at is None or now >= fixture_retry_at):
            try:
                fixture_schedule = load_fixture_schedule(config, now=now)
                checked_fixture_ids = set()
                fixture_retry_at = None
                LOGGER.info("Loaded local season fixture schedule")
            except AutomationError:
                LOGGER.exception("Local season fixture schedule load failed")
                fixture_retry_at = now + timedelta(minutes=15)
        alert_windows = ()
        if fixture_schedule is not None:
            try:
                alert_windows = fixture_alert_windows(
                    fixture_schedule,
                    now=now,
                    lead_minutes=config.lineup_alert_lead_minutes,
                    checked_event_ids=checked_fixture_ids,
                )
                due_ids = {
                    window.event_id
                    for window in alert_windows
                    if window.alert_at <= now < window.kickoff
                }
                if due_ids:
                    delivered = run_lineup_alerts(config, now=now, schedule=fixture_schedule)
                    checked_fixture_ids.update(due_ids)
                    if delivered:
                        LOGGER.info("Delivered %d lineup alert(s)", delivered)
            except AutomationError:
                LOGGER.exception("Lineup alert check failed")
        completed_minutes = {key for key in completed_minutes if key[1] == minute_key}
        next_alert = alert_windows[0].alert_at if alert_windows else None
        time.sleep(_sleep_until(now, _next_task_time(registry.tasks, now), fixture_retry_at, next_alert))


if __name__ == "__main__":
    raise SystemExit(main())
