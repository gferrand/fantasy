"""Behavior checks for quiet-day outlooks and truthful degradation."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fantasy_advisor.automation import (
    AutomationError, TaskSpec, _scheduled_response_payload, run_scheduled_advisor,
    split_discord_message,
)
from test_automation import watch_record, test_config as make_config


def packet():
    return {
        "season": "2026", "current_gameweek": 4, "last_completed_gameweek": 3,
        "players": [{
            "player_id": "one", "canonical_name": "Test Player",
            "current_identity": {"resolved": True, "current_club": "FUL", "current_positions": ["M"]},
            "current_sleeper_stats": {"found": True, "sleeper_standard_points": 4.5,
                                      "starts": 2, "minutes": 150, "points_per_game": 1.5},
            "next_fixture": {"opponent": "Opponent", "venue": "home",
                             "kickoff_utc": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()},
        }],
    }


def render(record=None, data=None):
    return _scheduled_response_payload(
        TaskSpec("watchlist_report", "Watchlist", Path("x"), "daily"),
        json.dumps({"status": "complete", "material_update": True, "report": "Discard me",
                    "research": [record or watch_record("one")]}),
        evidence="EVIDENCE\n" + json.dumps(data or packet()),
    )


def test_quiet_day_includes_outlook_evidence_production_and_watch_signal():
    report, material, status, _ = render()
    for expected in ("**Role:**", "**Availability:**", "**Outlook:**", "**Watch for:**",
                     "Sleeper standard: 4.5 pts", "150.0 minutes", "2.0 starts",
                     "Sleeper standard: 1.5 pts per appearance", "[Club report]", "vs Opponent",
                     "GW4", "last completed GW3", "ET"):
        assert expected in report
    assert "Discard me" not in report
    assert not material
    assert status == "no_change"
    assert all(len(chunk) <= 2000 for chunk in split_discord_message(report))


@pytest.mark.parametrize("outcome", ["insufficient_current_evidence", "research_failed"])
def test_partial_evidence_is_visible_and_keeps_deterministic_context(outcome):
    row = watch_record("one", outcome=outcome)
    row["availability"] = {"summary": "A current manager fitness statement could not be verified.",
                           "verified": False, "sources": []}
    report, _, status, _ = render(row)
    assert status == "partial"
    assert "Availability unverified" in report
    assert "4.5 pts" in report
    assert "**Watch for:**" in report


@pytest.mark.parametrize("field", ["role", "availability"])
def test_stale_or_undated_evidence_cannot_establish_current_status(field):
    for precision, stamp in [("date", "2025-01-01"), ("unknown", "")]:
        row = watch_record("one")
        row[field]["sources"][0].update(as_of=stamp, as_of_precision=precision)
        with pytest.raises(AutomationError, match="stale or missing"):
            render(row)


def test_near_fixture_needs_precise_availability_or_covering_timetable():
    data = packet()
    data["players"][0]["next_fixture"]["kickoff_utc"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    row = copy.deepcopy(watch_record("one"))
    source = row["availability"]["sources"][0]
    source.update(as_of=datetime.now(timezone.utc).date().isoformat(), as_of_precision="date")
    with pytest.raises(AutomationError, match="availability sources"):
        render(row, data)
    source.update(evidence_type="ongoing_timetable", covers_next_fixture=True)
    assert render(row, data)[2] == "no_change"


def test_missing_stats_and_unresolved_identity_do_not_erase_player_or_guess_fixture():
    data = packet()
    data["players"][0]["current_identity"] = {"resolved": False}
    data["players"][0]["current_sleeper_stats"] = {"found": False}
    report, _, _, _ = render(data=data)
    assert "Test Player" in report
    assert "Sleeper stats unavailable" in report
    assert "Current club/positions/fixture unavailable" in report
    assert "Opponent" not in report


@pytest.mark.parametrize("field", ["outlook", "watch_signal", "role", "availability"])
def test_generic_no_update_is_not_an_assessment(field):
    row = watch_record("one")
    value = "No material current public update found."
    if field in {"role", "availability"}:
        row[field]["summary"] = value
    else:
        row[field] = value
    with pytest.raises(AutomationError, match="specific|concrete"):
        render(row)


def test_material_news_and_supported_priority_are_visible():
    row = watch_record("one", outcome="verified_update")
    row["priority_reason"] = "Full training makes the next selection especially informative."
    report, material, status, _ = render(row)
    assert material and status == "complete"
    assert report.index("Attention priorities") < report.index("**Update:**")
    assert "return to full training" in report


def test_unsupported_priority_and_transaction_instruction_rejected():
    row = watch_record("one")
    row["priority_reason"] = "Follow the next lineup announcement."
    row["role"]["verified"] = row["availability"]["verified"] = False
    with pytest.raises(AutomationError, match="priority requires"):
        render(row)
    row = watch_record("one")
    row["outlook"] = "You should add him immediately for the upcoming fixture."
    with pytest.raises(AutomationError, match="transaction or lineup"):
        render(row)


def test_quality_retry_reports_actual_failure_then_renders_repaired_outlook():
    config = make_config()
    config = config.__class__(**{**config.__dict__, "openai_api_key": "test"})
    bad = watch_record("one")
    bad["watch_signal"] = "No material current public update found."
    def response(row):
        return MagicMock(output=[MagicMock(type="web_search_call")], id="test",
                         output_text=json.dumps({"status": "complete", "material_update": False,
                                                 "report": "Label", "research": [row]}))
    client = MagicMock()
    client.responses.create.side_effect = [response(bad), response(watch_record("one"))]
    result = run_scheduled_advisor(config, TaskSpec("watchlist_report", "Watchlist", Path("x"), "daily"),
                                   invocation="manual", evidence="EVIDENCE\n"+json.dumps(packet()),
                                   previous_state="No previous successful report is available.", client=client)
    assert "watch_signal" in client.responses.create.call_args.kwargs["input"]
    schema = client.responses.create.call_args.kwargs["text"]["format"]["schema"]["properties"]["research"]
    assert client.responses.create.call_args.kwargs["reasoning"] == {"effort": "high"}
    assert schema["minItems"] == schema["maxItems"] == 1
    assert schema["items"]["properties"]["player_id"]["enum"] == ["one"]
    assert result.trace["model_calls"] == 2
    assert "**Outlook:**" in result.text


def test_suspension_flag_is_not_hidden_by_active_catalog_status():
    data = packet()
    data["players"][0]["current_identity"]["status"] = "A"
    data["players"][0]["current_sleeper_stats"]["injury_status"] = "SUS"
    report, _, _, _ = render(data=data)
    assert "Sleeper availability flag: SUS" in report
    assert "status: A" not in report
    assert "season stats as retrieved" in report
    assert "stats through GW3" not in report


def test_sources_are_deduplicated_within_each_player_card():
    report, _, _, _ = render()
    assert report.count("https://club.example/report") == 1


def test_wordy_cards_are_rejected_instead_of_truncated():
    row = watch_record("one")
    row["outlook"] = "Regular minutes require further confirmation. " * 30
    with pytest.raises(AutomationError, match="110 narrative words"):
        render(row)


def test_too_many_attention_priorities_are_rejected():
    data = packet()
    rows = []
    for i in range(4):
        row = watch_record(str(i))
        row["priority_reason"] = "Recent starting role makes the next lineup informative."
        rows.append(row)
    data["players"] = [{**data["players"][0], "player_id": str(i)} for i in range(4)]
    with pytest.raises(AutomationError, match="at most three"):
        _scheduled_response_payload(
            TaskSpec("watchlist_report", "Watchlist", Path("x"), "daily"),
            json.dumps({"status": "complete", "material_update": False, "report": "Label", "research": rows}),
            evidence="EVIDENCE\n" + json.dumps(data),
        )


def test_invalid_source_reports_metadata_error_not_missing_player():
    row = watch_record("one", outcome="verified_update")
    row["sources"][0]["as_of_precision"] = "invalid"
    with pytest.raises(AutomationError, match="news source metadata"):
        render(row)


def test_second_quality_failure_stops_after_one_retry():
    config = make_config()
    config = config.__class__(**{**config.__dict__, "openai_api_key": "test"})
    bad = watch_record("one")
    bad["outlook"] = "No material current public update found."
    client = MagicMock()
    client.responses.create.return_value = MagicMock(
        output=[MagicMock(type="web_search_call")], id="test",
        output_text=json.dumps({"status": "complete", "material_update": False,
                                "report": "Label", "research": [bad]}),
    )
    with pytest.raises(AutomationError, match="concrete outlook"):
        run_scheduled_advisor(config, TaskSpec("watchlist_report", "Watchlist", Path("x"), "daily"),
                              invocation="manual", evidence="EVIDENCE\n"+json.dumps(packet()),
                              previous_state="none", client=client)
    assert client.responses.create.call_count == 2
