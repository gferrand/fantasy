from pathlib import Path

from fantasy_advisor.forecast_history import pending_actual_weeks, record_actuals, record_forecast


def test_forecast_history_keeps_prelock_snapshot_and_attaches_actuals(tmp_path: Path):
    payload = {
        "season": "2026", "gameweek": 4,
        "forecast": {"model_version": "sleeper-eb-v1", "projected_xi_player_ids": ["p"], "projected_xi_total": 8.4},
        "forecast_data": {"availability_research": {"p": {"sources": ["https://club.example"]}}},
        "your_team": {"players": [{"player_id": "p"}]}, "starting_slots": ["F"], "scoring_settings": {"pos_f_g": 4},
    }
    record_forecast(tmp_path, payload, retrieved_at="2026-09-01T00:00:00+00:00")
    assert pending_actual_weeks(tmp_path, before_season="2026", before_gameweek=5) == [("2026", 4)]
    record_actuals(tmp_path, season="2026", gameweek=4, actuals={"player_points": {"p": 9.0}})
    assert pending_actual_weeks(tmp_path, before_season="2026", before_gameweek=5) == []
