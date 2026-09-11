from datetime import datetime, timezone

from fantasy_advisor.availability import apply_availability_adjustments
from fantasy_advisor.forecast_model import MODEL_VERSION, historical_inputs
from fantasy_advisor.gameweek import _prepare_forecasts


SCORING = {"pos_f_g": 4, "pos_d_g": 8}


def _row(player_id, position, *, minutes, games, goals, club="ARS"):
    return {"player_id": player_id, "player": {"full_name": player_id, "team_abbr": club, "fantasy_positions": [position]}, "stats": {"min": minutes, "gp": games, f"pos_{position.lower()}_g": goals}}


def test_historical_inputs_current_is_primary_and_prior_stabilizes_rate():
    current = [_row("p", "F", minutes=90, games=1, goals=2), _row("peer", "F", minutes=900, games=10, goals=10)]
    prior = [_row("p", "F", minutes=900, games=10, goals=5)]
    signals = [{"player_id": "p", "positions": ["F"], "minutes": 90, "games": 1, "custom_points_per_90": 8.0}]
    historical_inputs(signals, current_rows=current, prior_rows=prior, recent_weekly_rows=[], scoring_settings=SCORING)
    signal = signals[0]
    assert signal["forecast_model_version"] == MODEL_VERSION
    assert 4.0 < signal["forecast_rate_per_90_input"] < 8.0
    assert signal["forecast_prior_row_available"] is True


def test_availability_is_source_required_and_preserves_if_active_forecast_inputs():
    signals = [{"player_id": "p", "injury_status": None, "forecast_expected_minutes_input": 80.0, "forecast_rate_per_90_input": 6.0}]
    apply_availability_adjustments(signals, {"players": [{"player_id": "p", "status": "GTD", "playing_probability": 0.5, "sources": ["https://club.example/news"]}]})
    assert signals[0]["forecast_expected_minutes_input"] == 80.0
    assert signals[0]["forecast_rate_per_90_input"] == 6.0
    assert signals[0]["injury_status"] == "GTD"
    apply_availability_adjustments(signals, {"players": [{"player_id": "p", "status": "OUT", "playing_probability": 1, "sources": []}]})
    assert signals[0]["forecast_expected_minutes_input"] == 80.0  # unsourced finding ignored


def test_roster_out_beats_conflicting_available_web_finding():
    signals = [{"player_id": "p", "injury_status": "OUT", "forecast_expected_minutes_input": 80.0}]
    apply_availability_adjustments(signals, {"players": [{"player_id": "p", "status": "AVAILABLE", "playing_probability": 1, "sources": ["https://club.example/news"]}]})
    assert signals[0]["injury_status"] == "OUT"
    assert signals[0]["availability_conflict"] is True


def test_out_and_gtd_keep_if_active_estimates_with_visible_labels():
    players = [
        {"player_id": "out", "name": "Out", "club": "ARS", "positions": ["F"], "injury_status": "OUT", "raw_stats": {"min": 90, "gp": 1, "pos_f_g": 2}},
        {"player_id": "gtd", "name": "GTD", "club": "ARS", "positions": ["F"], "injury_status": "GTD", "raw_stats": {"min": 90, "gp": 1, "pos_f_g": 2}},
    ]
    rows = [_row("out", "F", minutes=90, games=1, goals=2), _row("gtd", "F", minutes=90, games=1, goals=2)]
    schedule = {"events": [{"date": "2026-09-20T15:00:00Z", "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": "Arsenal"}}, {"homeAway": "away", "team": {"displayName": "Chelsea"}}]}]}]}
    forecast = _prepare_forecasts(players, scoring_settings=SCORING, starting_slots=["F"], fixture_schedule=schedule, now=datetime(2026, 9, 11, tzinfo=timezone.utc), current_rows=rows, prior_rows=[], recent_weekly_rows=[])
    assert players[0]["forecast"]["points"] is not None
    assert players[0]["forecast"]["display"].endswith("OUT")
    assert players[1]["forecast"]["points"] is not None
    assert players[1]["forecast"]["display"].endswith("GTD")
    assert forecast["projected_xi_total"] == players[1]["forecast"]["points"]
    assert forecast["projected_xi_player_ids"] == ["gtd"]
