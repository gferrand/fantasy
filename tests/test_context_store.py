import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import interactive_prompt, task_prompt_for_run, TaskSpec
from fantasy_advisor.context_store import (
    DISCORD_ASSISTANT_RESPONSE,
    DISCORD_USER_MESSAGE,
    SCHEDULED_REPORT,
    append_event,
    build_context_packet,
)


class ContextStoreTests(unittest.TestCase):
    def test_packet_combines_recent_discord_turns_and_scheduled_reports(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "advisor_context.sqlite3"
            append_event(
                database,
                kind=DISCORD_USER_MESSAGE,
                content="What did the latest recap say about my midfield?",
                created_at="2026-08-24T22:30:00+00:00",
            )
            append_event(
                database,
                kind=DISCORD_ASSISTANT_RESPONSE,
                content="The latest recap flagged the midfield minutes risk.",
                thread_id="thread-interactive",
                created_at="2026-08-24T22:30:10+00:00",
            )
            append_event(
                database,
                kind=SCHEDULED_REPORT,
                content="Nightly recap: pickup opportunities were checked.",
                task_id="nightly_recap",
                thread_id="thread-nightly",
                created_at="2026-08-24T22:00:00+00:00",
            )

            packet = build_context_packet(database)

            self.assertIn("RECENT DISCORD CONVERSATION", packet)
            self.assertIn("What did the latest recap say", packet)
            self.assertIn("The latest recap flagged", packet)
            self.assertIn("LATEST SCHEDULED REPORTS", packet)
            self.assertIn("Nightly recap: pickup opportunities", packet)
            self.assertIn("task=nightly_recap", packet)

    def test_packet_is_bounded_and_prefers_latest_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "advisor_context.sqlite3"
            append_event(database, kind=SCHEDULED_REPORT, content="old report", task_id="old")
            append_event(database, kind=SCHEDULED_REPORT, content="LATEST_REPORT_MARKER " * 400, task_id="latest")

            packet = build_context_packet(database, max_chars=1_500)

            self.assertLessEqual(len(packet), 1_500)
            self.assertIn("LATEST_REPORT_MARKER", packet)
            self.assertIn("SCHEDULED REPORT · latest", packet)

    def test_interactive_prompt_accepts_context_but_scheduled_prompt_does_not(self):
        interactive = interactive_prompt(
            "Follow up on that recommendation",
            context_packet="PERSISTED_MARKER",
        )
        self.assertIn("PERSISTED_MARKER", interactive)
        self.assertIn("Revalidate current", interactive)

        scheduled = task_prompt_for_run(
            TaskSpec(
                id="test",
                name="Test",
                prompt_file=ROOT / "docs" / "nightly_recap_task.md",
                schedule_type="daily",
            )
        )
        self.assertNotIn("PERSISTED_MARKER", scheduled)
        self.assertNotIn("PERSISTED FANTASY ADVISOR CONTEXT", scheduled)


if __name__ == "__main__":
    unittest.main()
