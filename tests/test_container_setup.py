import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ContainerSetupTests(unittest.TestCase):
    def test_image_is_source_built_for_the_scheduler_as_non_root(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertTrue(dockerfile.startswith("FROM python:3.12-slim-bookworm\n"))
        self.assertIn("COPY . /app", dockerfile)
        self.assertIn("python -m pip install --no-cache-dir .", dockerfile)
        self.assertIn("groupadd --system --gid 999 fantasy", dockerfile)
        self.assertIn("useradd --system --uid 999 --gid 999", dockerfile)
        self.assertIn("chown -R 999:999 /app", dockerfile)
        self.assertIn("USER fantasy", dockerfile)
        self.assertIn('["python", "-m", "fantasy_advisor.scheduler"]', dockerfile)
        self.assertNotIn("health-a47fb0b", dockerfile)

    def test_compose_preserves_the_scheduler_runtime_contract(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

        required = (
            "name: gf-fantasy",
            "  scheduler:",
            "context: .",
            "${FANTASY_SCHEDULER_IMAGE:-gf-fantasy-scheduler:local}",
            "${FANTASY_ENV_FILE:?set FANTASY_ENV_FILE to an external environment file}",
            "source: ${FANTASY_HOST_ROOT:?set FANTASY_HOST_ROOT to the canonical persistent root}/data",
            "source: ${FANTASY_HOST_ROOT:?set FANTASY_HOST_ROOT to the canonical persistent root}/reports",
            "create_host_path: false",
            '"host.docker.internal:host-gateway"',
            "mem_limit: 384m",
            "cpus: 0.25",
            "pids_limit: 128",
            "read_only: true",
            "no-new-privileges:true",
            "restart: unless-stopped",
            "/tmp:rw,noexec,nosuid,size=128m",
            '["CMD", "python", "-m", "fantasy_advisor.health", "--component", "scheduler"]',
            "interval: 60s",
            "timeout: 5s",
            "retries: 3",
            "start_period: 180s",
        )
        for value in required:
            self.assertIn(value, compose)
        self.assertIsNone(re.search(r"^\s+ports:\s*$", compose, re.MULTILINE))
        self.assertNotIn("discord", compose.lower())
        self.assertNotIn("health-a47fb0b", compose)
        self.assertEqual(compose.count("create_host_path: false"), 2)

    def test_private_and_persistent_paths_are_excluded_from_build_context(self):
        ignored = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())

        for entry in (".git", ".env", ".env.*", "*.env", ".venv", "venv", "data", "reports"):
            self.assertIn(entry, ignored)

    def test_operations_doc_is_honest_about_state_and_backups(self):
        operations = (ROOT / "docs" / "scheduler_compose.md").read_text(encoding="utf-8")
        normalized_operations = " ".join(operations.split())

        self.assertIn("retained prior image", normalized_operations)
        self.assertIn(
            "keeps the same `data/` and `reports/` bind mounts", normalized_operations
        )
        self.assertIn("are not backups", normalized_operations)
        self.assertIn("No backup system is configured", normalized_operations)
        self.assertIn("docker compose config --quiet", operations)
        self.assertIn("python -m fantasy_advisor.automation --list-tasks", operations)
        self.assertNotIn("docker compose logs", operations)
        self.assertNotIn("scheduler dry-run", operations)


if __name__ == "__main__":
    unittest.main()
