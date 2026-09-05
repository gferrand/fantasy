import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("install_automation", ROOT / "scripts" / "install_automation.py")
INSTALLER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(INSTALLER)


class InstallerTests(unittest.TestCase):
    def test_watchlist_task_generates_an_eight_am_launchd_definition(self):
        definitions = dict(INSTALLER.agent_definitions(repo_root=ROOT, python=ROOT / ".venv" / "bin" / "python"))
        watchlist = definitions["com.ginoferrand.fantasy.watchlist-report"]
        self.assertEqual(watchlist["StartCalendarInterval"], {"Hour": 8, "Minute": 0})
        self.assertIn("watchlist_report", " ".join(watchlist["ProgramArguments"]))

    def test_runtime_automation_data_is_seeded_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            (source / "automation").mkdir(parents=True)
            (source / "automation" / "watchlist.sqlite3").write_text("nine players")
            runtime.mkdir()

            self.assertTrue(INSTALLER.seed_runtime_automation_data(source, runtime))
            self.assertEqual(
                (runtime / "automation" / "watchlist.sqlite3").read_text(),
                "nine players",
            )

            (source / "automation" / "watchlist.sqlite3").write_text("stale checkout")
            self.assertFalse(INSTALLER.seed_runtime_automation_data(source, runtime))
            self.assertEqual(
                (runtime / "automation" / "watchlist.sqlite3").read_text(),
                "nine players",
            )

    @patch.object(INSTALLER.subprocess, "run")
    @patch.object(INSTALLER.shutil, "which", return_value="/usr/local/bin/docker")
    def test_running_fantasy_discord_containers_filters_other_projects(self, _which, run):
        run.return_value.returncode = 0
        run.return_value.stdout = (
            "gf-fantasy-discord-1\tgf-fantasy\n"
            "unrelated-discord-1\tunrelated\n"
        )

        self.assertEqual(
            INSTALLER.running_fantasy_discord_containers(),
            ("gf-fantasy-discord-1",),
        )


if __name__ == "__main__":
    unittest.main()
