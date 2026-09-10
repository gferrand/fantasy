"""Small container-native scheduler for the registered Fantasy tasks."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Collection
from zoneinfo import ZoneInfo

from .automation import AppConfig, AutomationError, TaskSpec, load_registry, run_scheduled_task
from .deadline_guardian import final_reminder_windows
from .health import HEARTBEAT_INTERVAL_SECONDS, MAX_BUSY_LEASE_SECONDS, write_health_state
from .lineup_alerts import fixture_alert_windows, load_fixture_schedule, run_deadline_guardian, run_lineup_alerts

LOGGER = logging.getLogger(__name__)
BUSY_LEASE_OVERHEAD_SECONDS = 180.0


def _is_due(task: TaskSpec, now: datetime) -> bool:
    if not task.enabled:
        return False
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
        if not task.enabled:
            continue
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


def _busy_lease_seconds(config: AppConfig) -> float:
    """Cover the configured task timeout plus bounded scheduler cleanup time."""

    return min(
        float(config.codex_timeout_seconds) + BUSY_LEASE_OVERHEAD_SECONDS,
        MAX_BUSY_LEASE_SECONDS,
    )


def _write_scheduler_health(
    config: AppConfig,
    unhealthy_components: Collection[str],
    *,
    busy: bool = False,
) -> None:
    """Publish idle activity or a bounded lease for one synchronous operation."""

    timestamp = time.time()
    write_health_state(
        config.repo_root,
        "scheduler",
        healthy=not unhealthy_components,
        unhealthy_components=unhealthy_components,
        now=timestamp,
        busy_until=timestamp + _busy_lease_seconds(config) if busy else None,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = AppConfig.from_environment()
    registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
    zone = ZoneInfo(registry.timezone)
    completed_minutes: set[tuple[str, str]] = set()
    fixture_schedule = None
    fixture_retry_at: datetime | None = None
    checked_fixture_ids: set[str] = set()
    unhealthy_components: set[str] = set()
    LOGGER.info("Fantasy container scheduler started for %s", registry.timezone)
    while True:
        now = datetime.now(zone)
        _write_scheduler_health(config, unhealthy_components)
        minute_key = now.isoformat()
        for task in registry.tasks:
            key = (task.id, minute_key)
            if key in completed_minutes or not _is_due(task, now):
                continue
            completed_minutes.add(key)
            _write_scheduler_health(config, unhealthy_components, busy=True)
            try:
                LOGGER.info("Starting scheduled task %s", task.id)
                run_scheduled_task(config, task.id)
                unhealthy_components.discard(f"task:{task.id}")
                LOGGER.info("Completed scheduled task %s", task.id)
            except AutomationError:
                unhealthy_components.add(f"task:{task.id}")
                LOGGER.exception("Scheduled task %s failed", task.id)
            finally:
                _write_scheduler_health(config, unhealthy_components)
        if fixture_schedule is None and (fixture_retry_at is None or now >= fixture_retry_at):
            _write_scheduler_health(config, unhealthy_components, busy=True)
            try:
                fixture_schedule = load_fixture_schedule(config, now=now)
                checked_fixture_ids = set()
                fixture_retry_at = None
                unhealthy_components.discard("fixture_schedule")
                LOGGER.info("Loaded local season fixture schedule")
            except AutomationError:
                unhealthy_components.add("fixture_schedule")
                LOGGER.exception("Local season fixture schedule load failed")
                fixture_retry_at = now + timedelta(minutes=15)
            finally:
                _write_scheduler_health(config, unhealthy_components)
        alert_windows = ()
        if fixture_schedule is not None:
            _write_scheduler_health(config, unhealthy_components, busy=True)
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
                unhealthy_components.discard("lineup_alerts")
            except AutomationError:
                unhealthy_components.add("lineup_alerts")
                LOGGER.exception("Lineup alert check failed")
            finally:
                _write_scheduler_health(config, unhealthy_components)
        guardian_windows = ()
        if fixture_schedule is not None:
            _write_scheduler_health(config, unhealthy_components, busy=True)
            try:
                guardian_windows = final_reminder_windows(
                    config,
                    now=now,
                    lead_minutes=config.deadline_guardian_final_lead_minutes,
                )
                if guardian_windows and guardian_windows[0] <= now:
                    delivered = run_deadline_guardian(config, now=now, schedule=fixture_schedule)
                    if delivered:
                        LOGGER.info("Delivered %d Deadline Guardian final reminder(s)", delivered)
                unhealthy_components.discard("deadline_guardian")
            except AutomationError:
                unhealthy_components.add("deadline_guardian")
                LOGGER.exception("Deadline Guardian final check failed")
            finally:
                _write_scheduler_health(config, unhealthy_components)
        completed_minutes = {key for key in completed_minutes if key[1] == minute_key}
        next_alert = alert_windows[0].alert_at if alert_windows else None
        next_guardian = guardian_windows[0] if guardian_windows else None
        _write_scheduler_health(config, unhealthy_components)
        sleep_seconds = _sleep_until(
            now, _next_task_time(registry.tasks, now), fixture_retry_at, next_alert, next_guardian
        )
        time.sleep(min(sleep_seconds, HEARTBEAT_INTERVAL_SECONDS))


if __name__ == "__main__":
    raise SystemExit(main())
