"""Durable, private audit records for deterministic Gameweek forecasts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping


def forecast_history_file(repo_root: Path) -> Path:
    return repo_root / "data" / "automation" / "forecast_history.sqlite3"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS gameweek_forecasts (
        season TEXT NOT NULL, gameweek INTEGER NOT NULL, model_version TEXT NOT NULL,
        retrieved_at TEXT NOT NULL, snapshot_json TEXT NOT NULL, actual_json TEXT,
        PRIMARY KEY (season, gameweek, model_version)
        )"""
    )
    return connection


def record_forecast(repo_root: Path, payload: Mapping[str, Any], *, retrieved_at: str) -> None:
    """Upsert the exact pre-lock model inputs, output XI, and availability packet."""
    forecast = payload.get("forecast") if isinstance(payload.get("forecast"), Mapping) else {}
    version = str(forecast.get("model_version") or payload.get("forecast_data", {}).get("model_version") or "unknown")
    snapshot = {
        "forecast": forecast,
        "forecast_data": payload.get("forecast_data", {}),
        "your_team": payload.get("your_team", {}),
        "starting_slots": payload.get("starting_slots", []),
        "scoring_settings": payload.get("scoring_settings", {}),
    }
    with _connect(forecast_history_file(repo_root)) as connection:
        connection.execute(
            """INSERT INTO gameweek_forecasts (season, gameweek, model_version, retrieved_at, snapshot_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(season, gameweek, model_version) DO UPDATE SET
               retrieved_at=excluded.retrieved_at, snapshot_json=excluded.snapshot_json""",
            (str(payload.get("season")), int(payload.get("gameweek") or 0), version, retrieved_at,
             json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False, default=str)),
        )


def record_actuals(repo_root: Path, *, season: str, gameweek: int, actuals: Mapping[str, Any]) -> None:
    """Attach a completed weekly Sleeper-score snapshot without rewriting inputs."""
    with _connect(forecast_history_file(repo_root)) as connection:
        connection.execute(
            "UPDATE gameweek_forecasts SET actual_json=? WHERE season=? AND gameweek=? AND actual_json IS NULL",
            (json.dumps(actuals, separators=(",", ":"), ensure_ascii=False, default=str), str(season), gameweek),
        )


def pending_actual_weeks(repo_root: Path, *, before_season: str, before_gameweek: int) -> list[tuple[str, int]]:
    """Return bounded completed forecast weeks that still need actual-score joins."""
    path = forecast_history_file(repo_root)
    if not path.exists():
        return []
    with _connect(path) as connection:
        rows = connection.execute(
            """SELECT DISTINCT season, gameweek FROM gameweek_forecasts
               WHERE actual_json IS NULL AND (season < ? OR (season = ? AND gameweek < ?))
               ORDER BY season DESC, gameweek DESC LIMIT 8""",
            (before_season, before_season, before_gameweek),
        ).fetchall()
    return [(str(season), int(gameweek)) for season, gameweek in rows]
