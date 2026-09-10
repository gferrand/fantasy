import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.health import (
    MAX_BUSY_LEASE_SECONDS,
    check_health,
    health_state_file,
    main,
    maintain_ready_heartbeat,
    write_health_state,
)


class HealthStateTests(unittest.TestCase):
    def test_fresh_healthy_heartbeat_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_health_state(root, "scheduler", now=1_000.0)

            payload = json.loads(health_state_file(root, "scheduler").read_text(encoding="utf-8"))
            self.assertEqual(
                payload,
                {
                    "schema_version": 1,
                    "component": "scheduler",
                    "status": "healthy",
                    "state": "idle",
                    "updated_at": 1_000.0,
                    "busy_until": None,
                    "unhealthy_components": [],
                },
            )

            result = check_health(root, "scheduler", now=1_030.0, max_age_seconds=60)

            self.assertTrue(result.healthy)
            self.assertEqual(result.reason, "heartbeat_fresh")
            self.assertEqual(result.age_seconds, 30.0)

    def test_missing_stale_and_reported_unhealthy_states_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(check_health(root, "discord", now=1_000.0).reason, "health_state_missing")

            write_health_state(root, "discord", now=1_000.0)
            self.assertEqual(
                check_health(root, "discord", now=1_181.0).reason,
                "health_state_stale",
            )

            write_health_state(
                root,
                "scheduler",
                healthy=False,
                unhealthy_components=("fixture_schedule",),
                now=1_180.0,
            )
            result = check_health(root, "scheduler", now=1_181.0)
            self.assertFalse(result.healthy)
            self.assertEqual(result.reason, "component_reported_unhealthy")

    def test_valid_busy_lease_survives_idle_staleness_but_expires(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_health_state(root, "scheduler", now=1_000.0, busy_until=1_300.0)

            active = check_health(root, "scheduler", now=1_200.0, max_age_seconds=60)
            expired = check_health(root, "scheduler", now=1_301.0, max_age_seconds=60)

            self.assertTrue(active.healthy)
            self.assertEqual(active.reason, "busy_lease_valid")
            self.assertEqual(active.state, "busy")
            self.assertEqual(active.busy_until, 1_300.0)
            self.assertFalse(expired.healthy)
            self.assertEqual(expired.reason, "busy_lease_expired")

    def test_busy_lease_keeps_prior_failure_unhealthy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_health_state(
                root,
                "scheduler",
                healthy=False,
                unhealthy_components=("fixture_schedule",),
                now=1_000.0,
                busy_until=1_300.0,
            )

            result = check_health(root, "scheduler", now=1_200.0, max_age_seconds=60)

            self.assertFalse(result.healthy)
            self.assertEqual(result.reason, "component_reported_unhealthy")
            self.assertEqual(result.state, "busy")

    def test_busy_lease_is_bounded_to_one_hour(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_health_state(
                root,
                "scheduler",
                now=1_000.0,
                busy_until=1_000.0 + MAX_BUSY_LEASE_SECONDS,
            )
            with self.assertRaisesRegex(ValueError, "within 3600 seconds"):
                write_health_state(
                    root,
                    "scheduler",
                    now=1_000.0,
                    busy_until=1_000.0 + MAX_BUSY_LEASE_SECONDS + 0.001,
                )

    def test_malformed_or_mismatched_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = health_state_file(root, "scheduler")
            path.parent.mkdir(parents=True)
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(check_health(root, "scheduler").reason, "health_state_unreadable")

            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "component": "discord",
                    "status": "healthy",
                    "updated_at": 1_000.0,
                }),
                encoding="utf-8",
            )
            self.assertEqual(
                check_health(root, "scheduler", now=1_000.0).reason,
                "health_state_invalid",
            )

    def test_probe_cli_returns_nonzero_json_for_stale_activity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_health_state(root, "scheduler", now=1_000.0)
            with (
                patch("fantasy_advisor.health.time.time", return_value=2_000.0),
                patch("builtins.print") as output,
            ):
                exit_code = main([
                    "--component", "scheduler",
                    "--repo-root", str(root),
                    "--max-age-seconds", "60",
                ])

            self.assertEqual(exit_code, 1)
            payload = json.loads(output.call_args.args[0])
            self.assertEqual(payload["status"], "unhealthy")
            self.assertEqual(payload["reason"], "health_state_stale")


class ReadyHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _closed_after_one_iteration():
        checks = iter((False, True))
        return lambda: next(checks)

    async def test_heartbeat_refreshes_while_client_is_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("fantasy_advisor.health.asyncio.sleep", new_callable=AsyncMock):
                await maintain_ready_heartbeat(
                    root,
                    "discord",
                    is_ready=lambda: True,
                    is_closed=self._closed_after_one_iteration(),
                    interval_seconds=0,
                )
            self.assertTrue(health_state_file(root, "discord").is_file())

    async def test_heartbeat_does_not_refresh_while_client_is_disconnected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("fantasy_advisor.health.asyncio.sleep", new_callable=AsyncMock):
                await maintain_ready_heartbeat(
                    root,
                    "discord",
                    is_ready=lambda: False,
                    is_closed=self._closed_after_one_iteration(),
                    interval_seconds=0,
                )
            self.assertFalse(health_state_file(root, "discord").exists())


if __name__ == "__main__":
    unittest.main()
