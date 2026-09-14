import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_advisor.automation import rotation_web_briefing_prompt
from fantasy_advisor.rotation import (
    DIFFICULT_FIXTURE_THRESHOLD,
    _has_reliable_role,
    _protected_players,
    _rank_drop_candidates,
    _rank_targets,
    _rank_trade_targets,
    rotation_moneyball_board,
    rotation_validation_failure_text,
)
from fantasy_advisor.interactive_advisor import _structured_finalization


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

    def test_targets_are_ranked_independently_without_forced_drops(self):
        easy = player("easy", "Easy Target", "GK", 12, 30, difficulty=2.0)
        hard = player("hard", "Hard Target", "F", 20, 40, difficulty=3.2)
        thin_sample = player("thin", "Thin Sample", "F", 20, 40, difficulty=2.0)
        thin_sample.update(minutes=45, starts=0, forecast_expected_minutes_per_fixture=45)

        targets = _rank_targets(
            [hard, thin_sample, easy],
            extended_by_id={row["player_id"]: row for row in [easy, hard, thin_sample]},
        )

        self.assertFalse(_has_reliable_role(thin_sample))
        self.assertEqual([target["player_id"] for target in targets], ["hard", "easy"])
        self.assertNotIn("drop", targets[0])
        self.assertEqual(targets[0]["fixture_quality"], "mixed_or_difficult")
        self.assertEqual(targets[1]["fixture_quality"], "favorable")
        self.assertEqual(targets[0]["ownership"], {
            "rostered": False, "team": None, "on_your_team": False,
        })

    def test_next_two_fixture_leader_gets_one_moneyball_screen_slot(self):
        rows = [
            player("d", "Projected Defender", "D", 20, 50, difficulty=3.0),
            player("gk", "Projected Keeper", "GK", 20, 45, difficulty=3.0),
            player("m", "Projected Mid", "M", 20, 40, difficulty=3.0),
            player("f", "Projected Forward", "F", 20, 35, difficulty=3.0),
            player("early", "Early Fixture Edge", "D", 20, 25, difficulty=3.2),
            player("next", "Next Projection", "D", 20, 30, difficulty=3.0),
        ]
        rows[4]["forecast_next_fixtures"] = [
            {"opponent": "A", "home": True, "difficulty": 2.0},
            {"opponent": "B", "home": False, "difficulty": 2.2},
            {"opponent": "C", "home": True, "difficulty": 4.2},
            {"opponent": "D", "home": False, "difficulty": 4.4},
        ]
        rows[4].update(minutes=270, starts=3)
        rows[5]["forecast_next_fixtures"] = [
            {"opponent": "A", "home": True, "difficulty": 1.5},
            {"opponent": "B", "home": False, "difficulty": 1.5},
        ]
        rows[5].update(minutes=90, starts=1)

        targets = _rank_targets(
            rows,
            extended_by_id={row["player_id"]: row for row in rows},
            limit=5,
        )

        self.assertEqual([target["player_id"] for target in targets], [
            "d", "gk", "m", "f", "early",
        ])
        self.assertEqual(targets[-1]["early_fixture_difficulty"], 2.1)

    def test_trade_targets_include_current_owner_but_no_offer(self):
        target = player("target", "Trade Target", "M", 15, 25, difficulty=2.5)
        targets = _rank_targets(
            [target],
            extended_by_id={"target": target},
            owners={"target": "Other Manager"},
        )

        self.assertEqual(targets[0]["current_fantasy_team"], "Other Manager")
        self.assertEqual(targets[0]["ownership"], {
            "rostered": True, "team": "Other Manager", "on_your_team": False,
        })
        self.assertNotIn("you_send", targets[0])

    def test_pickup_target_passes_the_real_recommendation_validator(self):
        target = player("pickup", "Pickup Target", "M", 15, 25, difficulty=2.5)
        evidence_target = _rank_targets(
            [target], extended_by_id={"pickup": target},
        )[0]
        rendered, trace = _structured_finalization(
            self._action_payload(evidence_target),
            {"data": {"pickup_targets": [evidence_target]}},
        )

        self.assertTrue(trace["target_verification_metadata_valid"])
        self.assertIn("Add Pickup Target", rendered)

    def test_trade_target_passes_the_real_recommendation_validator(self):
        target = player("trade", "Trade Target", "M", 15, 25, difficulty=2.5)
        evidence_target = _rank_targets(
            [target],
            extended_by_id={"trade": target},
            owners={"trade": "Other Manager"},
        )[0]
        rendered, trace = _structured_finalization(
            self._action_payload(evidence_target),
            {"data": {"trade_targets": [evidence_target]}},
        )

        self.assertTrue(trace["target_verification_metadata_valid"])
        self.assertIn("Trade for Trade Target", rendered)

    def test_validation_failure_text_retains_bounded_fixture_context(self):
        target = player("pickup", "Pickup Target", "M", 15, 25, difficulty=2.5)
        evidence_target = _rank_targets(
            [target], extended_by_id={"pickup": target},
        )[0]

        rendered = rotation_validation_failure_text({"pickup_targets": [evidence_target]})

        self.assertIn("internal recommendation check failed", rendered)
        self.assertIn("Deterministic fixture context (not recommendations)", rendered)
        self.assertIn("Pickup Target", rendered)
        self.assertIn("CHE (H)", rendered)
        self.assertNotIn("couldn’t verify current public", rendered)

    def test_moneyball_board_is_split_into_scannable_authoritative_lists(self):
        pickup_player = player("pickup", "Pickup Target", "D", 20, 30, difficulty=2.5)
        trade_player = player("trade", "Trade Target", "M", 15, 25, difficulty=2.8)
        pickup = _rank_targets(
            [pickup_player], extended_by_id={"pickup": pickup_player},
        )[0]
        trade = _rank_targets(
            [trade_player],
            extended_by_id={"trade": trade_player},
            owners={"trade": "Rival XI"},
        )[0]
        rendered = rotation_moneyball_board({
            "protected_players": [{"name": "Core Player", "reasons": ["best current XI"]}],
            "pickup_targets": [pickup],
            "trade_targets": [trade],
            "drop_candidates": [{"name": "Bench Player", "projected_horizon_points": 10}],
        })

        self.assertIn("**Keep — protected core**\n- **Core Player**", rendered)
        self.assertIn("**Free agents / waivers — acquisition screen**", rendered)
        self.assertIn("**Pickup Target** · ARS · D · unrostered", rendered)
        self.assertIn("**Trade targets — other teams**", rendered)
        self.assertIn("**Trade Target** · ARS · M · **Rival XI**", rendered)
        self.assertIn("Current: 15.0 K&R pts", rendered)
        self.assertIn("Next four: CHE (H)", rendered)
        self.assertIn("**Roster-space candidates — not automatic drops**", rendered)

    @staticmethod
    def _action_payload(target):
        return json.dumps({
            "analysis": "Current role and fixtures support this option.",
            "decision": {
                "actionable": True,
                "summary": "Act.",
                "targets": [{
                    "player_id": target["player_id"],
                    "name": target["name"],
                    "rationale": "Current evidence supports the move.",
                    "availability_injury_verified": True,
                    "role_minutes_verified": True,
                    "current_public_sources": [{
                        "title": "Official club",
                        "url": "https://example.com/current",
                    }],
                }],
            },
        })

    def test_trade_targets_exclude_top_quartile_premium_producers(self):
        players = [
            player("bruno", "Bruno Fernandes", "M", 75, 65, difficulty=2.5),
            player("steady", "Steady Starter", "D", 30, 42, difficulty=2.5),
            player("buy-low", "Buy Low", "M", 18, 45, difficulty=2.0),
            player("streamer", "Fixture Streamer", "F", 12, 36, difficulty=2.0),
        ]
        targets, cutoff = _rank_trade_targets(
            players,
            extended_by_id={row["player_id"]: row for row in players},
            owners={row["player_id"]: "Other Manager" for row in players},
        )

        target_ids = [target["player_id"] for target in targets]
        self.assertNotIn("bruno", target_ids)
        self.assertIn("buy-low", target_ids)
        self.assertLess(cutoff, 75)

    def test_target_list_preserves_positional_choice(self):
        defenders = [
            player(f"d{index}", f"Defender {index}", "D", 20, 50 - index, difficulty=2.0)
            for index in range(6)
        ]
        keeper = player("gk", "Goalkeeper Option", "GK", 10, 10, difficulty=2.5)
        rows = defenders + [keeper]

        targets = _rank_targets(
            rows,
            extended_by_id={row["player_id"]: row for row in rows},
            limit=5,
        )

        self.assertIn("gk", [target["player_id"] for target in targets])

    def test_drop_candidates_exclude_core_and_rank_weakest_first(self):
        core = player("core", "Core", "F", 50, 50)
        weak = player("weak", "Weak", "M", 2, 3, difficulty=3.5)
        stronger = player("stronger", "Stronger", "D", 10, 12, difficulty=2.5)

        drops = _rank_drop_candidates([core, stronger, weak], {"core"})

        self.assertEqual([item["player_id"] for item in drops], ["weak", "stronger"])

    def test_rotation_prompt_makes_core_and_read_only_rules_binding(self):
        context = json.dumps({
            "season": "2026",
            "gameweek": 4,
            "protected_players": [{"player_id": "core"}],
            "pickup_targets": [],
            "trade_targets": [],
            "drop_candidates": [],
        })
        prompt = rotation_web_briefing_prompt(live_context=context)

        self.assertIn("AUTOMATIC CORE PROTECTION IS BINDING", prompt)
        self.assertIn("next four fixtures", prompt)
        self.assertIn("Never attach or imply a drop", prompt)
        self.assertIn("Never make, simulate", prompt)
        self.assertIn("PICKUP OPTIONS", prompt)
        self.assertIn("TRADE TARGETS", prompt)
        self.assertIn("Never present", prompt)
        self.assertIn("premium star", prompt)
        self.assertIn("POSSIBLE DROPS / SHOP LIST", prompt)
        self.assertIn("known_non_epl_transfers", prompt)
        self.assertIn("must not be described as current teammates", prompt)
        self.assertIn("omit them", prompt)


if __name__ == "__main__":
    unittest.main()
