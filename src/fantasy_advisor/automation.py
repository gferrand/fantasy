"""Local task orchestration for the fantasy advisor.

The project owns the schedule. Each invocation starts a real local Codex CLI
task, captures its final response, and optionally delivers it through Discord.
The module deliberately uses only the standard library so the scheduler can
start before the optional Discord gateway dependency is imported.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import tomllib
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .context_store import SCHEDULED_REPORT, append_event, build_context_packet
from .watchlist import WatchlistPlayer, list_watchlist


ROOT = Path(os.environ.get("FANTASY_REPO_ROOT", Path(__file__).resolve().parents[2]))
DEFAULT_TASK_REGISTRY = ROOT / "automation" / "tasks.toml"
PROMPT_BLOCK_RE = re.compile(r"```text\s*\n(?P<prompt>.*?)\n```", re.DOTALL)
LIVE_COMPACT_FEED_URL = "https://gferrand.github.io/fantasy/sleeper_feed.json"
LIVE_AVAILABILITY_FEED_URL = "https://gferrand.github.io/fantasy/sleeper_available_players.json"
LIVE_PLAYER_INDEX_URL = "https://gferrand.github.io/fantasy/sleeper_player_index.json"
EXPECTED_LEAGUE_ID = "1378147559444348928"
EXPECTED_MANAGER_ID = "1127171221277331456"
MAX_COMPACT_FEED_BYTES = 200_000
FANTASY_CODEX_MODEL = "gpt-5.6-luna"
FANTASY_CODEX_REASONING_EFFORT = "medium"


class AutomationError(RuntimeError):
    """Raised for a local automation configuration or execution failure."""


@dataclass(frozen=True)
class TaskSpec:
    id: str
    name: str
    prompt_file: Path
    schedule_type: str
    run_at: str | None = None
    minute_past_hour: int | None = None
    state_file: Path | None = None


@dataclass(frozen=True)
class TaskRegistry:
    timezone: str
    tasks: tuple[TaskSpec, ...]

    def get(self, task_id: str) -> TaskSpec:
        for task in self.tasks:
            if task.id == task_id:
                return task
        available = ", ".join(task.id for task in self.tasks) or "none"
        raise AutomationError(f"Unknown task {task_id!r}; available tasks: {available}")


@dataclass(frozen=True)
class AppConfig:
    repo_root: Path
    task_registry_path: Path
    discord_bot_token: str | None
    discord_allowed_user_id: str | None
    discord_scheduled_channel_id: str | None
    codex_bin: str
    codex_model: str | None
    codex_reasoning_effort: str | None
    codex_sandbox: str
    codex_timeout_seconds: int
    codex_ephemeral: bool
    codex_interactive_timeout_seconds: int = 180
    host_executor_url: str | None = None
    host_executor_token: str | None = None
    openai_api_key: str | None = None
    openai_audio_transcription_model: str = "gpt-4o-mini-transcribe"
    openai_document_model: str = "gpt-4.1-mini"

    @classmethod
    def from_environment(
        cls,
        *,
        repo_root: Path = ROOT,
        env_file: Path | None = None,
        task_registry_path: Path | None = None,
    ) -> "AppConfig":
        load_env_file(env_file or repo_root / ".env")
        timeout_text = os.environ.get("CODEX_TIMEOUT_SECONDS", "1800")
        interactive_timeout_text = os.environ.get("CODEX_INTERACTIVE_TIMEOUT_SECONDS", "120")
        try:
            timeout = int(timeout_text)
        except ValueError as exc:
            raise AutomationError("CODEX_TIMEOUT_SECONDS must be an integer") from exc
        if timeout < 1:
            raise AutomationError("CODEX_TIMEOUT_SECONDS must be positive")
        try:
            interactive_timeout = int(interactive_timeout_text)
        except ValueError as exc:
            raise AutomationError("CODEX_INTERACTIVE_TIMEOUT_SECONDS must be an integer") from exc
        if interactive_timeout < 1:
            raise AutomationError("CODEX_INTERACTIVE_TIMEOUT_SECONDS must be positive")
        return cls(
            repo_root=repo_root,
            task_registry_path=task_registry_path or repo_root / "automation" / "tasks.toml",
            discord_bot_token=os.environ.get("DISCORD_BOT_TOKEN", "").strip() or None,
            discord_allowed_user_id=os.environ.get("DISCORD_ALLOWED_USER_ID", "").strip() or None,
            discord_scheduled_channel_id=(
                os.environ.get("DISCORD_SCHEDULED_CHANNEL_ID", "").strip() or None
            ),
            openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip() or None,
            openai_audio_transcription_model=(
                os.environ.get("OPENAI_AUDIO_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe").strip()
                or "gpt-4o-mini-transcribe"
            ),
            openai_document_model=(
                os.environ.get("OPENAI_DOCUMENT_MODEL", "gpt-4.1-mini").strip()
                or "gpt-4.1-mini"
            ),
            codex_bin=os.environ.get("CODEX_BIN", "codex").strip() or "codex",
            codex_model=FANTASY_CODEX_MODEL,
            codex_reasoning_effort=FANTASY_CODEX_REASONING_EFFORT,
            codex_sandbox=os.environ.get("CODEX_SANDBOX", "read-only").strip() or "read-only",
            codex_timeout_seconds=timeout,
            codex_ephemeral=parse_bool(os.environ.get("CODEX_EPHEMERAL", "false")),
            codex_interactive_timeout_seconds=interactive_timeout,
            host_executor_url=os.environ.get("GF_HOST_EXECUTOR_URL", "").strip() or None,
            host_executor_token=os.environ.get("GF_HOST_EXECUTOR_TOKEN", "").strip() or None,
        )

    def require_discord(self) -> None:
        if not self.discord_bot_token:
            raise AutomationError("DISCORD_BOT_TOKEN is not configured")
        if not self.discord_allowed_user_id:
            raise AutomationError("DISCORD_ALLOWED_USER_ID is not configured")
        if not self.discord_allowed_user_id.isdigit():
            raise AutomationError("DISCORD_ALLOWED_USER_ID must be a numeric Discord user ID")

    def require_scheduled_discord(self) -> None:
        if not self.discord_bot_token:
            raise AutomationError("DISCORD_BOT_TOKEN is not configured")
        if not self.discord_scheduled_channel_id:
            raise AutomationError("DISCORD_SCHEDULED_CHANNEL_ID is not configured")
        if not self.discord_scheduled_channel_id.isdigit():
            raise AutomationError("DISCORD_SCHEDULED_CHANNEL_ID must be a numeric Discord channel ID")


@dataclass(frozen=True)
class CodexResult:
    text: str
    thread_id: str | None
    elapsed_seconds: float


class CodexRunError(AutomationError):
    """Raised when a Codex task exits unsuccessfully or emits no final text."""


class CodexRunner:
    """Launch the installed Codex CLI in a controlled, non-interactive task."""

    def __init__(self, config: AppConfig):
        self.config = config

    def command(self, output_file: Path, *, ephemeral: bool | None = None) -> list[str]:
        command = [self.config.codex_bin, "--search", "exec"]
        if self.config.codex_model:
            command.extend(("--model", self.config.codex_model))
        if self.config.codex_reasoning_effort:
            command.extend(
                (
                    "--config",
                    f'model_reasoning_effort="{self.config.codex_reasoning_effort}"',
                )
            )
        command.extend(
            (
                "--sandbox",
                self.config.codex_sandbox,
                "--skip-git-repo-check",
                "--json",
                "--color",
                "never",
                "--output-last-message",
                str(output_file),
                "-C",
                str(self.config.repo_root),
            )
        )
        use_ephemeral = self.config.codex_ephemeral if ephemeral is None else ephemeral
        if use_ephemeral:
            command.append("--ephemeral")
        command.append("-")
        return command

    def run(
        self,
        prompt: str,
        *,
        label: str,
        timeout_seconds: int | None = None,
        ephemeral: bool | None = None,
    ) -> CodexResult:
        if not prompt.strip():
            raise CodexRunError(f"Cannot run empty Codex prompt for {label}")
        timeout = timeout_seconds if timeout_seconds is not None else self.config.codex_timeout_seconds
        if timeout < 1:
            raise CodexRunError(f"Codex timeout for {label!r} must be positive")
        started = time.monotonic()
        if self.config.host_executor_url:
            return self._run_on_host_executor(prompt, label=label, timeout=timeout, started=started)
        with tempfile.TemporaryDirectory(prefix="fantasy-codex-") as temporary:
            temporary_path = Path(temporary)
            output_file = temporary_path / "last-message.txt"
            command = self.command(output_file, ephemeral=ephemeral)
            try:
                process = subprocess.Popen(
                    command,
                    text=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.config.repo_root,
                    start_new_session=True,
                )
                try:
                    events, diagnostics = process.communicate(input=prompt, timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    # Codex can give its code-mode host a separate process
                    # group. Capture descendants before terminating the parent
                    # so a timeout cannot leave that helper behind.
                    descendant_pids = descendant_process_ids(process.pid)
                    terminate_process_tree(process.pid, descendant_pids, signal.SIGTERM)
                    try:
                        events, diagnostics = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        terminate_process_tree(process.pid, descendant_pids, signal.SIGKILL)
                        events, diagnostics = process.communicate()
                    raise CodexRunError(
                        f"Codex task {label!r} exceeded {timeout}s"
                    ) from exc
            except FileNotFoundError as exc:
                raise CodexRunError(
                    f"Codex executable not found: {self.config.codex_bin}"
                ) from exc

            text = output_file.read_text(encoding="utf-8").strip() if output_file.exists() else ""
            if not text:
                text = final_message_from_events(events)
            thread_id = thread_id_from_events(events)
            if process.returncode != 0:
                detail = (diagnostics or events).strip()
                detail = detail[-2000:] if detail else "no diagnostic output"
                raise CodexRunError(
                    f"Codex task {label!r} failed with exit code {process.returncode}: {detail}"
                )
            if not text:
                raise CodexRunError(f"Codex task {label!r} completed without a final message")
            return CodexResult(
                text=text,
                thread_id=thread_id,
                elapsed_seconds=round(time.monotonic() - started, 2),
            )

    def _run_on_host_executor(self, prompt: str, *, label: str, timeout: int, started: float) -> CodexResult:
        if not self.config.host_executor_token:
            raise CodexRunError("Host Codex executor is configured without its authentication token")
        request = Request(
            self.config.host_executor_url.rstrip("/") + "/v1/execute",
            data=json.dumps(
                {
                    "app": "fantasy",
                    "prompt": prompt,
                    "model": self.config.codex_model or "",
                    "reasoning_effort": self.config.codex_reasoning_effort or "",
                    "sandbox": self.config.codex_sandbox,
                    "timeout_seconds": timeout,
                }
            ).encode(),
            headers={"Content-Type": "application/json", "X-GF-Executor-Secret": self.config.host_executor_token},
            method="POST",
        )
        try:
            with urlopen(request, timeout=max(5, min(timeout + 15, 1815))) as response:
                body = json.loads(response.read().decode())
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise CodexRunError(f"Host Codex executor could not complete {label!r}") from exc
        if body.get("status") != "completed":
            raise CodexRunError(f"Host Codex executor failed {label!r}")
        text = str((body.get("result") or {}).get("response") or "").strip()
        if not text:
            raise CodexRunError(f"Host Codex executor completed {label!r} without a final message")
        return CodexResult(text=text, thread_id=None, elapsed_seconds=round(time.monotonic() - started, 2))


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding the parent environment."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def parse_bool(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise AutomationError(f"Expected a boolean value, got {value!r}")


def load_registry(path: Path, *, repo_root: Path = ROOT) -> TaskRegistry:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutomationError(f"Task registry not found: {path}") from exc
    settings = raw.get("settings") or {}
    tasks: list[TaskSpec] = []
    for item in raw.get("tasks") or []:
        try:
            task_id = str(item["id"])
            prompt_file = (repo_root / str(item["prompt_file"])).resolve()
            schedule_type = str(item["schedule_type"])
        except KeyError as exc:
            raise AutomationError(f"Task registry entry is missing {exc.args[0]!r}") from exc
        if repo_root not in prompt_file.parents:
            raise AutomationError(f"Prompt file escapes the repository: {prompt_file}")
        tasks.append(
            TaskSpec(
                id=task_id,
                name=str(item.get("name") or task_id),
                prompt_file=prompt_file,
                schedule_type=schedule_type,
                run_at=str(item["run_at"]) if item.get("run_at") is not None else None,
                minute_past_hour=(
                    int(item["minute_past_hour"])
                    if item.get("minute_past_hour") is not None
                    else None
                ),
                state_file=(
                    (repo_root / str(item["state_file"])).resolve()
                    if item.get("state_file") is not None
                    else None
                ),
            )
        )
        if tasks[-1].state_file is not None and repo_root not in tasks[-1].state_file.parents:
            raise AutomationError(f"State file escapes the repository: {tasks[-1].state_file}")
    if not tasks:
        raise AutomationError(f"Task registry contains no tasks: {path}")
    return TaskRegistry(timezone=str(settings.get("timezone", "America/New_York")), tasks=tuple(tasks))


def prompt_from_markdown(path: Path) -> str:
    document = path.read_text(encoding="utf-8")
    match = PROMPT_BLOCK_RE.search(document)
    if not match:
        raise AutomationError(f"No ```text``` prompt block found in {path}")
    return match.group("prompt").strip()


def task_prompt(task: TaskSpec) -> str:
    return prompt_from_markdown(task.prompt_file)


def task_prompt_for_run(task: TaskSpec, *, runtime_context: str | None = None) -> str:
    """Add bounded local history when a recurring task needs change detection."""

    prompt = task_prompt(task)
    execution_contract = (
        "LOCAL SCHEDULER EXECUTION CONTRACT\n"
        "This prompt is being executed now by the project's local scheduler. "
        "The schedule has already fired. Do not create, edit, enable, disable, "
        "or describe any ChatGPT/OpenAI scheduled task, and do not answer with a "
        "setup confirmation. Perform the requested briefing or monitor now and "
        "return only its report."
    )
    prompt = f"{execution_contract}\n\n{prompt}"
    if runtime_context and runtime_context.strip():
        prompt = f"{prompt}\n\n{runtime_context.strip()}\n"
    if task.state_file is None:
        return prompt
    if task.state_file.exists():
        previous = task.state_file.read_text(encoding="utf-8").strip()
        previous = previous[-12000:] if previous else "(The previous result was empty.)"
        history = (
            "A previous successful local run is included below. It is only a "
            "change-detection aid, not current-source evidence. Revalidate every "
            "claim against current sources and report only material changes.\n\n"
            "PREVIOUS LOCAL RESULT:\n"
            f"{previous}"
        )
    else:
        history = "There is no previous local result yet; treat this as the first run."
    return f"{prompt}\n\nLOCAL RUN HISTORY\n{history}\n"


def persist_task_state(task: TaskSpec, result: CodexResult) -> None:
    if task.state_file is None:
        return
    task.state_file.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"# Last successful local result for `{task.id}`\n\n"
        f"Codex task: `{result.thread_id or 'local'}`\n\n"
        f"{result.text.strip()}\n"
    )
    temporary = task.state_file.with_suffix(task.state_file.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(task.state_file)


def _validate_compact_feed(payload: object) -> dict[str, Any]:
    """Validate the minimum contract needed for a Discord advisory snapshot."""

    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value is not an object")
    if payload.get("schema_version") != 1:
        raise ValueError("schema_version is not 1")
    if payload.get("complete") is not True:
        raise ValueError("complete is not true")
    if str(payload.get("league_id")) != EXPECTED_LEAGUE_ID:
        raise ValueError("league_id does not match this advisor")
    if not isinstance(payload.get("retrieved_at"), str) or not payload["retrieved_at"].strip():
        raise ValueError("retrieved_at is missing")
    league = payload.get("league")
    if not isinstance(league, dict) or not isinstance(league.get("season"), str):
        raise ValueError("league season is missing")
    return payload


def _decode_compact_feed(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_COMPACT_FEED_BYTES:
        raise ValueError(f"feed exceeds {MAX_COMPACT_FEED_BYTES} bytes")
    return _validate_compact_feed(json.loads(raw.decode("utf-8")))


def _load_live_compact_feed(config: AppConfig) -> tuple[dict[str, Any], str]:
    """Fetch the compact feed with its explicit local fallback."""

    failures: list[str] = []
    request = Request(LIVE_COMPACT_FEED_URL, headers={"User-Agent": "FantasyAdvisor/1.0"})
    try:
        with urlopen(request, timeout=20) as response:  # nosec B310: fixed public URL
            return _decode_compact_feed(response.read(MAX_COMPACT_FEED_BYTES + 1)), LIVE_COMPACT_FEED_URL
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"live feed: {exc}")
    local_feed = config.repo_root / "public" / "sleeper_feed.json"
    try:
        return _decode_compact_feed(local_feed.read_bytes()), f"local fallback `{local_feed}`"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"local fallback: {exc}")
    raise AutomationError("Could not load current Sleeper feed: " + "; ".join(failures))


def load_current_epl_player_index(config: AppConfig) -> list[dict[str, Any]]:
    """Load the small published index used by Discord watch commands."""

    failures: list[str] = []
    sources = (
        (LIVE_PLAYER_INDEX_URL, config.repo_root / "public" / "sleeper_player_index.json"),
    )
    for live_url, local_path in sources:
        try:
            request = Request(live_url, headers={"User-Agent": "FantasyAdvisor/1.0"})
            with urlopen(request, timeout=20) as response:  # nosec B310: fixed public URL
                payload = _decode_compact_feed(response.read(MAX_COMPACT_FEED_BYTES + 1))
        except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"live index: {exc}")
            try:
                payload = _decode_compact_feed(local_path.read_bytes())
            except (OSError, ValueError, json.JSONDecodeError) as local_exc:
                failures.append(f"local index: {local_exc}")
                continue
        players = payload.get("players")
        if not isinstance(players, list) or not players:
            failures.append("player index has no players")
            continue
        valid = [
            player for player in players
            if isinstance(player, dict)
            and str(player.get("player_id") or "").strip()
            and str(player.get("name") or "").strip()
            and str(player.get("club") or "").strip()
        ]
        if len(valid) != len(players):
            failures.append("player index has malformed players")
            continue
        return valid
    raise AutomationError("Current Premier League player index is unavailable: " + "; ".join(failures))


def premier_league_evidence_window(payload: dict[str, Any]) -> str:
    """Render the binding current-season evidence scope from a live feed."""

    league = payload.get("league")
    season = league.get("season") if isinstance(league, dict) else None
    if not isinstance(season, str) or not re.fullmatch(r"\d{4}", season):
        raise ValueError("league season is not a four-digit year")
    start_year = int(season)
    season_label = f"{start_year}/{str(start_year + 1)[-2:]}"
    state = payload.get("state")
    round_number = payload.get("round")
    if isinstance(state, dict) and isinstance(state.get("display_week"), int):
        round_number = state["display_week"]
    round_label = f"through GW{round_number}" if isinstance(round_number, int) else "through the live feed"
    return (
        "ACTIVE EVIDENCE WINDOW (binding)\n"
        f"Season: {season_label}\n"
        "Competition: Premier League only\n"
        f"Coverage: {round_label}\n"
        f"Snapshot retrieved: {payload['retrieved_at']}\n"
        "Do not use previous-season, preseason, cup, European, youth, or generic career "
        "statistics as evidence for current Premier League minutes, appearances, form, "
        "availability, or role."
    )


def availability_question(question: str) -> bool:
    normalized = question.casefold()
    return any(term in normalized for term in ("available", "pickup", "waiver", "free agent", "free-agent", "add"))


def load_live_compact_feed_context(config: AppConfig, *, include_availability: bool = False) -> str:
    """Fetch a small, validated live league snapshot for one Discord task.

    Codex CLI tasks need not have a browser or shell tool. Supplying the bounded
    feed directly keeps their work focused on advice rather than large retrieval
    or parsing jobs. The local copy is deliberately a clearly labelled fallback.
    """

    try:
        payload, source = _load_live_compact_feed(config)
    except AutomationError as exc:
        return "LIVE COMPACT SLEEPER FEED\nUnavailable before the Codex task began. " + str(exc)
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    packet = (
        "LIVE COMPACT SLEEPER FEED (already fetched and validated by the Discord gateway)\n"
        f"Source: {source}\n"
        f"Retrieved at: {payload['retrieved_at']}\n"
        f"{premier_league_evidence_window(payload)}\n"
        "Use this packet as the current league source. Do not fetch or reconstruct the "
        "full Sleeper player pool yourself.\n"
        "JSON:\n"
        f"{rendered}"
    )
    if not include_availability:
        return packet

    shortlist = payload.get("available_players")
    if not isinstance(shortlist, list) or not shortlist:
        return packet + "\n\nLIVE AVAILABILITY SHORTLIST\nUnavailable in the compact feed."
    return (
        packet
        + "\n\nLIVE AVAILABILITY SHORTLIST (pre-scored, bounded current-season candidates)\n"
        + "This is intentionally not the full player pool. Use it only to identify up to six finalists.\nJSON:\n"
        + json.dumps(shortlist, ensure_ascii=False, separators=(",", ":"))
    )


def load_interactive_live_feed_context(config: AppConfig, *, include_availability: bool = False) -> str:
    """Return only the user's relevant roster data to an interactive Codex task.

    Passing every compact-feed roster, player and stat record still creates a
    45KB prompt. That invited unbounded analysis and caused routine Discord
    questions to time out. The gateway retains the complete feed locally but
    gives Codex the current user's roster, scoring map, and bounded candidate
    shortlist only.
    """

    try:
        payload, source = _load_live_compact_feed(config)
    except AutomationError as exc:
        return "LIVE INTERACTIVE SLEEPER FEED\nUnavailable before the Codex task began. " + str(exc)
    users = payload.get("users") if isinstance(payload.get("users"), list) else []
    team_name = next(
        (
            str(user.get("team_name") or user.get("display_name") or "Los Blancos")
            for user in users
            if isinstance(user, dict) and str(user.get("user_id")) == EXPECTED_MANAGER_ID
        ),
        "Los Blancos",
    )
    rosters = payload.get("rosters") if isinstance(payload.get("rosters"), list) else []
    roster = next(
        (
            item for item in rosters
            if isinstance(item, dict) and str(item.get("owner_id")) == EXPECTED_MANAGER_ID
        ),
        {},
    )
    roster_ids = [str(player_id) for player_id in (roster.get("players") or [])]
    player_map = payload.get("players") if isinstance(payload.get("players"), dict) else {}
    stats_by_id: dict[str, dict[str, Any]] = {}
    for row in payload.get("stats") or []:
        if isinstance(row, dict) and isinstance(row.get("stats"), dict):
            stats_by_id[str(row.get("player_id") or "")] = row["stats"]
    roster_players = []
    for player_id in roster_ids:
        player = player_map.get(player_id)
        if not isinstance(player, dict):
            continue
        stat_row = stats_by_id.get(player_id, {})
        roster_players.append(
            {
                "player_id": player_id,
                "name": player.get("name"),
                "club": player.get("club"),
                "positions": player.get("positions") or [],
                "injury_status": player.get("injury_status"),
                "injury_notes": player.get("injury_notes"),
                "current_season_summary": {
                    key: stat_row[key]
                    for key in ("gp", "gs", "min", "pts_std", "rank_std")
                    if key in stat_row
                },
            }
        )
    league = payload["league"]
    compact = {
        "retrieved_at": payload["retrieved_at"],
        "league": {
            "name": league.get("name"),
            "season": league.get("season"),
            "scoring_settings": league.get("scoring_settings") or {},
            "roster_positions": league.get("roster_positions") or [],
        },
        "state": payload.get("state"),
        "round": payload.get("round"),
        "your_team": {"name": team_name, "players": roster_players},
    }
    if include_availability:
        compact["available_player_shortlist"] = payload.get("available_players") or []
        compact["team_swap_recommendations"] = payload.get("team_swap_recommendations") or []
        compact["team_swap_recommendations_note"] = payload.get(
            "team_swap_recommendations_note"
        )
    return (
        "LIVE INTERACTIVE SLEEPER FEED (bounded roster-specific snapshot)\n"
        f"Source: {source}\n"
        f"{premier_league_evidence_window(payload)}\n"
        "This is the complete current context needed for ordinary roster questions. "
        "Do not reconstruct the full league player pool.\nJSON:\n"
        + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    )


def descendant_process_ids(parent_pid: int) -> list[int]:
    """Return currently live descendants of a process, deepest first."""

    try:
        listing = subprocess.run(
            ["ps", "-axo", "pid=,ppid="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, ppid = (int(value) for value in parts)
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    result: list[int] = []
    pending = list(children.get(parent_pid, []))
    while pending:
        pid = pending.pop()
        result.append(pid)
        pending.extend(children.get(pid, []))
    return list(reversed(result))


def terminate_process_tree(parent_pid: int, descendants: list[int], signal_number: int) -> None:
    """Best-effort termination for a timed-out Codex CLI process and helpers."""

    for pid in descendants:
        try:
            os.kill(pid, signal_number)
        except ProcessLookupError:
            pass
    try:
        os.killpg(parent_pid, signal_number)
    except ProcessLookupError:
        pass


def interactive_prompt(
    question: str,
    *,
    context_packet: str | None = None,
    live_feed_packet: str | None = None,
    waiver_analysis: bool = False,
) -> str:
    persisted_context = ""
    if context_packet and context_packet.strip():
        persisted_context = f"""

PERSISTED CONTEXT FROM THIS FANTASY ADVISOR:
{context_packet.strip()}

Use this material to understand references to earlier Discord answers and
scheduled reports. It is background context, not current-source evidence.
Revalidate current player, fixture, injury, club, and availability facts before
making a recommendation.
"""
    feed_context = ""
    if live_feed_packet and live_feed_packet.strip():
        feed_context = f"""

{live_feed_packet.strip()}
"""
    waiver_report_rules = """
For this dedicated waiver-analysis request, present the entire supplied
`available_player_shortlist` in compact ranked form: rank, player, club,
positions, current custom points, and minutes. Then present every supplied
`team_swap_recommendations` signal with the potential add, possible drop,
shared position, and current-season scoring gap. Give a concise recommendation
summary after those lists. The swap signals are manual-review candidates only;
never claim that a Sleeper transaction occurred.
""" if waiver_analysis else """
For pickup questions, assess no more than six candidates from the compact
shortlist. For a question about fit, compare those candidates against the
current Los Blancos roster, open position needs, and custom scoring in the
feed.
"""
    return f"""You are my read-only fantasy EPL advisor running as a local Codex task.

Read `league_context.md` before answering. Preserve its safety rules: never make,
simulate, or imply a Sleeper transaction; I make all final decisions manually.
The Discord gateway normally supplies a compact, validated live Sleeper feed
below. Use that packet as the current league source; do not assume browser,
network, or shell tools are available inside this Codex task.
The `ACTIVE EVIDENCE WINDOW` in that packet is binding for every player-specific
claim. For minutes, appearances, form, role, injuries, availability, or likely
starts, use only evidence explicitly about the active Premier League season and
competition. A source's publication date alone is not enough: it must clearly
identify the active season or the relevant current Premier League match. Never
use 2025/26, preseason, cup, European, youth, or career data as a proxy for
2026/27 Premier League evidence unless the user explicitly asks for historical
or non-Premier-League context.

If verified current-season Premier League evidence is unavailable or ambiguous,
say `Not verified for the active Premier League season` and do not make a
minutes, appearance, or form claim from an older source. Do not turn a
prior-season review into a current-season projection.

For every player-specific current-season claim, include a compact `Evidence
window:` line with the active season, `Premier League`, and the current gameweek
or snapshot cutoff, followed by direct source links. Before finalizing, remove
any claim whose source does not pass this season-and-competition check.
When an `available_player_shortlist` is present, it is the bounded candidate
pool for a pickup or availability question. Select and explain up to six
finalists from it; do not attempt a full-pool scan.

When `team_swap_recommendations` is present, use it only as a bounded,
current-season, same-position scoring signal. Verify role, injury status,
fixture context, and the Sleeper Add option before recommending a manual swap;
never imply that a transaction occurred.

Do not read or download `data/sleeper_snapshot.json`, the raw Sleeper
`/players/clubsoccer:epl` endpoint, or the full availability supplement. Those
payloads are intentionally large and can turn a simple advisory request into an
unbounded data-processing task. If the supplied feed is unavailable, explain
that constraint; never attempt a full-pool reconstruction.

{waiver_report_rules}
Do not use stale context, search snippets, or standard FPL scoring. Use current reputable football
sources only to verify a small number of finalists where that could materially
change the recommendation.
Separate confirmed facts from inference, include source links for current claims,
and state clearly when data cannot be validated. Keep the answer concise,
decision-oriented, and bounded: return the best available answer promptly;
never keep exploring data after you have enough evidence to answer.

INTERACTIVE TIME BUDGET (binding): return a useful answer within 75 seconds.
Use at most two targeted web searches or source-page opens in total, and do not
perform broad research, multi-source surveys, or repeated searches. If current
evidence cannot be verified in that budget, say so explicitly and answer from
the supplied live roster snapshot where possible. Never delay the response to
chase more evidence.
{feed_context}
{persisted_context}

The user request is below. Answer it directly; do not modify repository files.

USER REQUEST:
{question.strip()}
"""


def final_message_from_events(events: str) -> str:
    messages: list[str] = []
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            value = item.get("text")
            if isinstance(value, str) and value.strip():
                messages.append(value.strip())
    return messages[-1] if messages else ""


def thread_id_from_events(events: str) -> str | None:
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and event.get("thread_id"):
            return str(event["thread_id"])
    return None


def split_discord_message(text: str, *, limit: int = 2000) -> list[str]:
    if limit < 1:
        raise ValueError("Discord message limit must be positive")
    remaining = text.strip()
    if not remaining:
        return [""]
    chunks: list[str] = []
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    chunks.append(remaining)
    return chunks


def build_report_header(task: TaskSpec, result: CodexResult) -> str:
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return f"**{task.name}** · {timestamp} · Codex task `{result.thread_id or 'local'}`\n\n"


def advisor_context_file(config: AppConfig) -> Path:
    """Return the private event database shared by local automation processes."""

    return config.repo_root / "data" / "automation" / "advisor_context.sqlite3"


def watchlist_file(config: AppConfig) -> Path:
    """Return the private database reserved for the personal watchlist."""

    return config.repo_root / "data" / "automation" / "watchlist.sqlite3"


def build_watchlist_live_packet(config: AppConfig) -> str | None:
    """Build bounded current data for watched players only.

    Scheduled watchlist reports deliberately bypass the Discord context store.
    A missing current index does not erase a saved player: it makes the player
    explicitly out of the active Premier League index for this report.
    """

    watched = list_watchlist(watchlist_file(config))
    if not watched:
        return None
    try:
        feed, feed_source = _load_live_compact_feed(config)
        current_index = {player["player_id"]: player for player in load_current_epl_player_index(config)}
    except AutomationError as exc:
        raise AutomationError(f"Could not build watchlist live packet: {exc}") from exc

    stats = feed.get("stats")
    stats_by_player: dict[str, list[dict[str, Any]]] = {}
    if isinstance(stats, list):
        for row in stats:
            if not isinstance(row, dict):
                continue
            player_id = str(row.get("player_id") or "").strip()
            if player_id:
                stats_by_player.setdefault(player_id, []).append(row)
    players: list[dict[str, Any]] = []
    for watched_player in watched:
        current = current_index.get(watched_player.player_id)
        players.append(
            {
                "player_id": watched_player.player_id,
                "canonical_name": watched_player.name,
                "club_when_added": watched_player.club,
                "positions_when_added": list(watched_player.positions),
                "added_at": watched_player.added_at,
                "active_in_current_premier_league_index": current is not None,
                "current_sleeper_metadata": current,
                "current_season_stat_rows": stats_by_player.get(watched_player.player_id, []),
            }
        )
    packet = {
        "watchlist_source": str(watchlist_file(config)),
        "watchlist_count": len(players),
        "feed_source": feed_source,
        "feed_retrieved_at": feed["retrieved_at"],
        "league": feed["league"],
        "state": feed.get("state"),
        "round": feed.get("round"),
        "evidence_window": premier_league_evidence_window(feed),
        "players": players,
    }
    return (
        "PERSONAL WATCHLIST LIVE SNAPSHOT (assembled before this task; it contains no Discord conversation context)\n"
        "Use only these watched players. Current Sleeper metadata and stat rows are source data, "
        "not a license to infer missing Premier League appearances or minutes.\n"
        "JSON:\n"
        + json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    )


def load_advisor_context(config: AppConfig) -> str:
    """Load context for an interactive Discord task only."""

    try:
        return build_context_packet(advisor_context_file(config))
    except Exception as exc:
        raise AutomationError(f"Could not load advisor context: {exc}") from exc


def persist_advisor_context_event(
    config: AppConfig,
    *,
    kind: str,
    content: str,
    task_id: str | None = None,
    thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist one context event with the automation error boundary applied."""

    try:
        append_event(
            advisor_context_file(config),
            kind=kind,
            content=content,
            task_id=task_id,
            thread_id=thread_id,
            metadata=metadata,
        )
    except Exception as exc:
        raise AutomationError(f"Could not persist advisor context: {exc}") from exc


def outbox_directory(config: AppConfig) -> Path:
    return config.repo_root / "data" / "automation" / "outbox"


def discord_channel_state_file(config: AppConfig) -> Path:
    """Return the ignored file holding the last personal bot-DM channel."""

    return config.repo_root / "data" / "automation" / "discord_dm_channel.txt"


def discord_ready_state_file(config: AppConfig) -> Path:
    """Return the ignored file used to mark a connected Discord gateway."""

    return config.repo_root / "data" / "automation" / "discord_ready.txt"


def persist_discord_ready_state(config: AppConfig) -> None:
    path = discord_ready_state_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(f"{time.time():.6f}\n", encoding="utf-8")
    temporary.replace(path)


def read_discord_channel_id(config: AppConfig) -> str | None:
    path = discord_channel_state_file(config)
    if not path.exists():
        return None
    channel_id = path.read_text(encoding="utf-8").strip()
    return channel_id if channel_id.isdigit() else None


def persist_discord_channel_id(config: AppConfig, channel_id: str) -> None:
    if not channel_id.isdigit():
        raise AutomationError("Discord DM channel ID must be numeric")
    path = discord_channel_state_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(f"{channel_id}\n", encoding="utf-8")
    temporary.replace(path)


def persist_outbox_report(config: AppConfig, task: TaskSpec, result: CodexResult, report: str) -> Path:
    """Persist a report before attempting network delivery."""

    return persist_outbox_message(config, task.id, result.thread_id, report)


def persist_outbox_message(
    config: AppConfig,
    task_id: str,
    thread_id: str | None,
    report: str,
) -> Path:
    """Persist any scheduled message before attempting network delivery."""

    outbox = outbox_directory(config)
    outbox.mkdir(parents=True, exist_ok=True)
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)
    safe_thread_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", thread_id or "local")
    target = outbox / f"{time.time_ns()}-{safe_task_id}-{safe_thread_id}.md"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(target)
    return target


def flush_outbox(config: AppConfig, transport: Any) -> None:
    """Deliver reports left by a prior run, deleting each only after success."""

    outbox = outbox_directory(config)
    if not outbox.exists():
        return
    for report_file in sorted(outbox.glob("*.md")):
        report = report_file.read_text(encoding="utf-8").strip()
        if not report:
            raise AutomationError(f"Scheduled report outbox file is empty: {report_file}")
        transport.send_channel(config.discord_scheduled_channel_id, report)
        report_file.unlink()


def run_scheduled_task(
    config: AppConfig,
    task_id: str,
    *,
    deliver: bool = True,
    persist_state: bool = True,
    persist_context: bool = True,
) -> CodexResult:
    registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
    task = registry.get(task_id)
    runtime_context = build_watchlist_live_packet(config) if task.id == "watchlist_report" else None
    if task.id == "watchlist_report" and runtime_context is None:
        # An empty personal watchlist is intentionally silent: no Codex task,
        # state update, conversation event, or misleading Discord DM.
        return CodexResult(text="WATCHLIST_EMPTY", thread_id=None, elapsed_seconds=0.0)
    transport = None
    if deliver:
        config.require_scheduled_discord()
        from .discord_transport import DiscordTransport

        transport = DiscordTransport(config.discord_bot_token)
        flush_outbox(config, transport)
    try:
        result = CodexRunner(config).run(
            task_prompt_for_run(task, runtime_context=runtime_context),
            label=task.id,
        )
    except AutomationError as exc:
        if deliver:
            try:
                failure_report = f"**{task.name} failed**\n\n{str(exc)[-2000:]}"
                failure_file = persist_outbox_message(config, task.id, "failed", failure_report)
                transport.send_channel(config.discord_scheduled_channel_id, failure_report)
                failure_file.unlink()
            except AutomationError:
                # Preserve the Codex failure in launchd's stderr if Discord is
                # also unavailable; the next scheduled run can retry cleanly.
                pass
        raise
    if persist_state:
        persist_task_state(task, result)
    report = build_report_header(task, result) + result.text
    if persist_context:
        # Scheduled prompts intentionally do not read Discord context. Their
        # completed reports become reference material for future interactive
        # Discord tasks only after the scheduled Codex run has finished.
        persist_advisor_context_event(
            config,
            kind=SCHEDULED_REPORT,
            content=report,
            task_id=task.id,
            thread_id=result.thread_id,
            metadata={"source": "scheduled_task", "delivered": deliver},
        )
    if deliver:
        report_file = persist_outbox_report(config, task, result, report)
        transport.send_channel(config.discord_scheduled_channel_id, report)
        report_file.unlink()
    return result


def run_interactive_task(
    config: AppConfig,
    question: str,
    *,
    context_packet: str | None = None,
    waiver_analysis: bool = False,
) -> CodexResult:
    """Run an interactive task with an optional Discord-built context packet."""

    return CodexRunner(config).run(
        interactive_prompt(
            question,
            context_packet=context_packet,
            waiver_analysis=waiver_analysis,
            live_feed_packet=load_interactive_live_feed_context(
                config,
                include_availability=waiver_analysis or availability_question(question),
            ),
        ),
        label="discord-query",
        timeout_seconds=config.codex_interactive_timeout_seconds,
        # Conversation continuity is held in the local context store. Avoid
        # persistent Codex task state for short Discord requests so a damaged
        # CLI session cannot affect the next message.
        ephemeral=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local fantasy Codex task")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--task", help="registered scheduled task ID")
    choice.add_argument("--query", help="one-off read-only question for a new Codex task")
    choice.add_argument("--list-tasks", action="store_true", help="list registered tasks")
    parser.add_argument("--dry-run", action="store_true", help="run without sending to Discord")
    parser.add_argument("--print-prompt", action="store_true", help="print the prompt and exit")
    args = parser.parse_args(argv)

    config = AppConfig.from_environment()
    registry = load_registry(config.task_registry_path, repo_root=config.repo_root)
    if args.list_tasks:
        for task in registry.tasks:
            print(f"{task.id}\t{task.name}\t{task.schedule_type}")
        return 0

    if args.task:
        task = registry.get(args.task)
        prompt = task_prompt(task)
        if args.print_prompt:
            print(prompt)
            return 0
        result = run_scheduled_task(
            config,
            args.task,
            deliver=not args.dry_run,
            persist_state=not args.dry_run,
            persist_context=not args.dry_run,
        )
        if args.dry_run:
            print(result.text)
        return 0

    if not args.query or not args.query.strip():
        raise AutomationError("--query must not be empty")
    prompt = interactive_prompt(args.query)
    if args.print_prompt:
        print(prompt)
        return 0
    result = run_interactive_task(config, args.query)
    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
