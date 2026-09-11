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
    """Attach verified availability without changing an if-active forecast.

    The Gameweek number answers the useful counterfactual, "what could this
    player score if he plays?" Availability controls the legal XI and the
    visible status marker instead.  This keeps an OUT player from silently
    looking like a zero-point player while still keeping him out of the total.
    """
    findings = validated_availability_packet(packet)
    for signal in signals:
        finding = findings.get(str(signal.get("player_id")))
        if finding is None:
            continue
        status = finding["status"]
        signal["availability_research"] = finding
        # A roster-level OUT/IR/suspension flag is a stronger reason not to
        # start a player than a conflicting generic web availability result.
        # Keep the visible status truthful until the roster feed changes.
        if str(signal.get("injury_status") or "").upper() in INACTIVE and status not in INACTIVE:
            signal["availability_conflict"] = True
            continue
        signal["injury_status"] = "SUSP" if status == "SUSPENDED" else status
    return findings
