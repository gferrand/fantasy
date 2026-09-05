import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import rotation_web_briefing_prompt
from fantasy_advisor.rotation import (
    DIFFICULT_FIXTURE_THRESHOLD,
    _available_options,
    _filter_rotation_trades,
    _is_reliable_incoming,
    _mix_moves,
    _protected_players,
)


def player(player_id, name, position, current, projected, *, injury=None, difficulty=3.0):
    return {
        "player_id": player_id,
        "name": name,
        "club": "ARS",
        "positions": [position],
        "position_points": {position: current},
        "current_custom_points": current,
        "projected_horizon_points": projected,
        "scoring_data_available": True,
        "injury_status": injury,
        "minutes": 180,
        "starts": 2,
        "forecast_horizon_fixtures": 4,
        "forecast_expected_minutes_per_fixture": 90,
        "forecast_fixture_difficulty": difficulty,
        "forecast_next_fixtures": [
            {"opponent": "CHE", "home": True, "difficulty": difficulty}
        ] * 4,
    }


class RotationTests(unittest.TestCase):
    def test_difficult_fixture_threshold_marks_runs_above_neutral(self):
        self.assertEqual(DIFFICULT_FIXTURE_THRESHOLD, 3.1)

    def test_core_is_union_of_current_projected_lineups_and_medical_holds(self):
        roster = [
            player("current", "Current Core", "F", 50, 5),
            player("future", "Future Core", "F", 10, 60),
            player("injured", "Injured Hold", "F", 1, 1, injury="OUT"),
        ]
        protected, rows = _protected_players(roster, ("F",))

        self.assertEqual(protected, {"current", "future", "injured"})
        reasons = {row["player_id"]: row["reasons"] for row in rows}
        self.assertIn("best current XI", reasons["current"])
        self.assertIn("best projected four-fixture XI", reasons["future"])
        self.assertEqual(reasons["injured"], ["medical hold"])

    def test_available_swap_never_drops_protected_player_and_requires_lineup_gain(self):
        roster = [
            player("core", "Core Forward", "F", 50, 20),
            player("fringe", "Fringe Forward", "F", 2, 1),
        ]
        target = player("target", "Fixture Target", "F", 12, 30, difficulty=2.0)
        options = _available_options(
            roster,
            [target],
            ("F",),
            {"core"},
            {"target": target},
        )

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["drop"]["player_id"], "fringe")
        self.assertEqual(options[0]["projected_lineup_gain"], 10.0)

        weak = player("weak", "Weak Target", "F", 5, 21)
        self.assertEqual(
            _available_options(roster, [weak], ("F",), {"core"}, {"weak": weak}),
            [],
        )

    def test_top_five_mix_reserves_both_acquisition_paths(self):
        available = [
            {"kind": "available", "projected_lineup_gain": gain}
            for gain in (10, 9, 8, 7)
        ]
        trades = [
            {"kind": "trade", "math": {"your_projected_lineup_gain": gain}}
            for gain in (6, 5, 4)
        ]

        mixed = _mix_moves(available, trades)

        self.assertEqual(len(mixed), 5)
        self.assertEqual([item["kind"] for item in mixed].count("trade"), 2)
        self.assertEqual([item["kind"] for item in mixed].count("available"), 3)

    def test_available_target_needs_role_evidence_and_easier_fixtures(self):
        roster = [
            player("core", "Core Forward", "F", 50, 20),
            player("fringe", "Fringe Forward", "F", 2, 1, difficulty=3.4),
        ]
        thin_sample = player("thin", "Thin Sample", "F", 20, 40, difficulty=2.0)
        thin_sample.update(minutes=45, starts=0, forecast_expected_minutes_per_fixture=45)
        hard_run = player("hard", "Hard Run", "F", 20, 40, difficulty=3.2)
        not_easier = player("same", "Same Fixtures", "F", 20, 40, difficulty=3.3)

        self.assertFalse(_is_reliable_incoming(thin_sample))
        self.assertEqual(
            _available_options(
                roster,
                [thin_sample, hard_run, not_easier],
                ("F",),
                {"core"},
                {row["player_id"]: row for row in [thin_sample, hard_run, not_easier]},
            ),
            [],
        )

    def test_rotation_trade_requires_material_gain_role_and_fixture_edge(self):
        receive = player("in", "Incoming", "F", 20, 35, difficulty=2.5)
        send = player("out", "Outgoing", "F", 20, 20, difficulty=3.2)
        viable = {
            "kind": "trade",
            "you_receive": [receive],
            "you_send": [send],
            "math": {"your_projected_lineup_gain": 8},
        }
        weak = {**viable, "math": {"your_projected_lineup_gain": 2}}
        stale_role = {**viable, "you_receive": [{**receive, "starts": 0}]}

        self.assertEqual(_filter_rotation_trades([viable, weak, stale_role]), [viable])

    def test_rotation_prompt_makes_core_and_read_only_rules_binding(self):
        context = json.dumps({
            "season": "2026",
            "gameweek": 4,
            "protected_players": [{"player_id": "core"}],
            "recommended_moves": [],
        })
        prompt = rotation_web_briefing_prompt(live_context=context)

        self.assertIn("AUTOMATIC CORE PROTECTION IS BINDING", prompt)
        self.assertIn("next four fixtures", prompt)
        self.assertIn("five total supplied moves", prompt)
        self.assertIn("Never make, simulate", prompt)
        self.assertIn("AVAILABLE / WAIVERS", prompt)
        self.assertIn("TRADE TARGETS", prompt)
        self.assertIn("known_non_epl_transfers", prompt)
        self.assertIn("must not be described as current teammates", prompt)
        self.assertIn("omit them", prompt)


if __name__ == "__main__":
    unittest.main()
