import importlib.util
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
