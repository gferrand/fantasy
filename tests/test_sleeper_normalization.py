import unittest
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fantasy_advisor.sleeper import (
    available_epl_players,
    available_stats_backed_players,
    normalize_completed_trades,
    transactions_url,
)


class SleeperNormalizationTests(unittest.TestCase):
    def test_transactions_url_requires_numeric_round(self):
        self.assertEqual(
            transactions_url("league-1", 3),
            "https://api.sleeper.app/v1/league/league-1/transactions/3",
        )
        with self.assertRaises(ValueError):
            transactions_url("league-1", 0)

    def test_normalize_completed_trades_filters_and_reconstructs_sides(self):
        created = int(
            datetime(2026, 8, 22, 14, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
            * 1000
        )
        transactions = [
            {
                "transaction_id": "trade-1",
                "type": "trade",
                "status": "complete",
                "created": created,
                "roster_ids": [1, 2],
                "adds": {"101": 2},
                "drops": {"202": 2, "303": 1},
                "draft_picks": [{"season": "2027", "round": 4}],
                "waiver_budget": [{"sender": 1, "receiver": 2, "amount": 5}],
            },
            {"transaction_id": "trade-1", "type": "trade", "status": "complete", "created": created},
            {"transaction_id": "pending", "type": "trade", "status": "pending", "created": created},
            {"transaction_id": "waiver", "type": "free_agent", "status": "complete", "created": created},
        ]
        players = {
            "101": {"full_name": "Incoming Player"},
            "202": {"full_name": "Outgoing Player"},
            "303": {"full_name": "Second Outgoing Player"},
        }

        result = normalize_completed_trades(
            transactions,
            day=datetime(2026, 8, 22).date(),
            roster_names={1: "Team A", 2: "Team B"},
            players=players,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["transaction_id"], "trade-1")
        self.assertEqual(result[0]["sides"][0]["team"], "Team A")
        self.assertEqual(
            [item["name"] for item in result[0]["sides"][0]["sends"]],
            ["Second Outgoing Player"],
        )
        self.assertEqual(
            [item["name"] for item in result[0]["sides"][1]["receives"]],
            ["Incoming Player"],
        )

    def test_available_players_are_owned_and_current_epl_only(self):
        players = {
            "owned": {
                "player_id": "owned",
                "full_name": "Owned Player",
                "team_abbr": "ARS",
                "competitions": ["epl"],
                "active": True,
                "status": "A",
                "fantasy_positions": ["M"],
            },
            "free": {
                "player_id": "free",
                "full_name": "Available Player",
                "team_abbr": "ARS",
                "competitions": ["epl"],
                "active": True,
                "status": "A",
                "fantasy_positions": ["F"],
            },
            "transferred": {
                "player_id": "transferred",
                "full_name": "Mohamed Salah",
                "team_abbr": "LIV",
                "competitions": ["epl"],
                "active": True,
                "status": "A",
                "fantasy_positions": ["F"],
            },
            "inactive": {
                "player_id": "inactive",
                "full_name": "Inactive Player",
                "team_abbr": "ARS",
                "competitions": ["epl"],
                "active": False,
                "status": "I",
                "fantasy_positions": ["F"],
            },
        }

        result = available_epl_players(
            players,
            [{"players": ["owned"]}],
            excluded_names={"Mohamed Salah"},
        )

        self.assertEqual([item["name"] for item in result], ["Available Player"])
        self.assertEqual(result[0]["availability"], "unrostered_unclassified")

    def test_stats_backed_fallback_is_bounded_and_labeled(self):
        rows = [
            {
                "player_id": "free",
                "stats": {"pos_f_g": 1},
                "player": {
                    "full_name": "Stats Player",
                    "team_abbr": "ARS",
                    "active": True,
                    "status": "A",
                    "fantasy_positions": ["F"],
                },
            },
            {
                "player_id": "owned",
                "player": {
                    "full_name": "Owned Stats Player",
                    "team_abbr": "ARS",
                    "active": True,
                    "status": "A",
                    "fantasy_positions": ["F"],
                },
            },
        ]

        result = available_stats_backed_players(rows, [{"players": ["owned"]}])

        self.assertEqual([item["name"] for item in result], ["Stats Player"])
        self.assertEqual(result[0]["candidate_source"], "current-season-stats")


if __name__ == "__main__":
    unittest.main()
