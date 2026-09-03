"""Small container-native scheduler for the registered Fantasy tasks."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .automation import AppConfig, AutomationError, TaskSpec, load_registry, run_scheduled_task
from .lineup_alerts import run_lineup_alerts

LOGGER = logging.getLogger(__name__)


def _is_due(task: TaskSpec, now: datetime) -> bool:
    if task.schedule_type == "hourly":
        return task.minute_past_hour == now.minute
    if task.schedule_type == "daily" and task.run_at:
        hour, minute = (int(part) for part in task.run_at.split(":", 1))
        return now.hour == hour and now.minute == minute
    return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = AppConfig.from_environment()
    registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
    zone = ZoneInfo(registry.timezone)
    completed_minutes: set[tuple[str, str]] = set()
    LOGGER.info("Fantasy container scheduler started for %s", registry.timezone)
    while True:
        now = datetime.now(zone).replace(second=0, microsecond=0)
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
        try:
            delivered = run_lineup_alerts(config, now=now)
            if delivered:
                LOGGER.info("Delivered %d lineup alert(s)", delivered)
        except AutomationError:
            LOGGER.exception("Lineup alert check failed")
        completed_minutes = {key for key in completed_minutes if key[1] == minute_key}
        time.sleep(max(1, 60 - datetime.now(zone).second))


if __name__ == "__main__":
    raise SystemExit(main())
