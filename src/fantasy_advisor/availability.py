"""Validation and bounded minutes-only availability adjustments."""

from __future__ import annotations

from typing import Any, Mapping


VALID_STATUSES = {"AVAILABLE", "GTD", "DOUBTFUL", "OUT", "SUSPENDED", "ROLE_UNCERTAIN"}
INACTIVE = {"OUT", "SUSPENDED", "IR"}


def validated_availability_packet(packet: object) -> dict[str, dict[str, Any]]:
    """Keep only current, source-backed player availability findings.

    An unlinked or malformed model/web result must be a no-op rather than a
    hidden opinion that changes a numeric forecast.
    """
    entries = packet.get("players") if isinstance(packet, Mapping) else None
    if not isinstance(entries, list):
        return {}
    valid: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        player_id = str(entry.get("player_id") or "").strip()
        status = str(entry.get("status") or "").upper().strip()
        sources = entry.get("sources")
        probability = entry.get("playing_probability")
        if not player_id or status not in VALID_STATUSES or not isinstance(sources, list):
            continue
        source_links = [str(source) for source in sources if isinstance(source, str) and source.startswith("https://")]
        if not source_links:
            continue
        if not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
            continue
        valid[player_id] = {"status": status, "playing_probability": float(probability), "sources": source_links[:3]}
    return valid


def apply_availability_adjustments(signals: list[dict[str, Any]], packet: object) -> dict[str, dict[str, Any]]:
    """Apply verified status to minutes only; production rate is untouched."""
    findings = validated_availability_packet(packet)
    for signal in signals:
        finding = findings.get(str(signal.get("player_id")))
        if finding is None:
            continue
        status = finding["status"]
        signal["availability_research"] = finding
        if status in INACTIVE:
            signal["injury_status"] = "SUSP" if status == "SUSPENDED" else "OUT"
            signal["forecast_expected_minutes_input"] = 0.0
        else:
            signal["forecast_expected_minutes_input"] = round(
                float(signal.get("forecast_expected_minutes_input") or 0.0) * finding["playing_probability"], 1
            )
            if status == "GTD":
                signal["injury_status"] = "GTD"
    return findings
