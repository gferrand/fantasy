#!/usr/bin/env python3
"""Install or preview the fantasy advisor's macOS launchd agents."""

from __future__ import annotations

import argparse
import io
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = Path.home() / "Library" / "Logs"
PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON_GATE = ROOT / "scripts" / "run_python_after_startup.sh"
RUNTIME_ROOT = Path.home() / "Library" / "Application Support" / "FantasyAdvisor" / "runtime"
AGENT_PREFIX = "com.ginoferrand.fantasy"


def running_fantasy_discord_containers() -> tuple[str, ...]:
    """Return running Compose Discord services that can race this listener."""

    if shutil.which("docker") is None:
        return ()
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.service=discord",
            "--format",
            '{{.Names}}\t{{.Label "com.docker.compose.project"}}',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return ()
    matches: list[str] = []
    for line in result.stdout.splitlines():
        name, _, project = line.partition("\t")
        if "fantasy" in name.lower() or "fantasy" in project.lower():
            matches.append(name)
    return tuple(matches)


def seed_runtime_automation_data(source_data: Path, runtime_data: Path) -> bool:
    """Seed mutable local state once without overwriting an existing runtime."""

    source = source_data / "automation"
    destination = runtime_data / "automation"
    if destination.exists():
        return False
    if source.exists():
        shutil.copytree(source, destination, symlinks=True)
        return True
    destination.mkdir(parents=True, exist_ok=True)
    return False


def task_registry(repo_root: Path) -> tuple[Any, ...]:
    sys.path.insert(0, str(repo_root / "src"))
    from fantasy_advisor.automation import load_registry

    return load_registry(repo_root / "automation" / "tasks.toml", repo_root=repo_root).tasks


def agent_definitions(
    *,
    python: Path = PYTHON,
    repo_root: Path = ROOT,
    tasks: tuple[Any, ...] | None = None,
    python_gate: Path | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Return the explicit launchd definitions owned by this project."""

    python_gate = python_gate or (repo_root / "scripts" / "run_python_after_startup.sh")
    environment = {
        "HOME": str(Path.home()),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "FANTASY_PYTHON": str(python),
        "PYTHONUNBUFFERED": "1",
        "TZ": "America/New_York",
    }
    common: dict[str, Any] = {
        "WorkingDirectory": str(repo_root),
        "EnvironmentVariables": environment,
        "ProcessType": "Background",
        "ThrottleInterval": 30,
    }
    definitions = [
        (
            f"{AGENT_PREFIX}.discord",
            {
                **common,
                "Label": f"{AGENT_PREFIX}.discord",
                "ProgramArguments": gated_program_arguments(
                    ["-m", "fantasy_advisor.discord_bot"], gate=python_gate
                ),
                "RunAtLoad": True,
                "KeepAlive": True,
                "StandardOutPath": str(LOG_DIR / "fantasy-discord-bot.log"),
                "StandardErrorPath": str(LOG_DIR / "fantasy-discord-bot.error.log"),
            },
        ),
    ]
    for task in tasks if tasks is not None else task_registry(repo_root):
        label = f"{AGENT_PREFIX}.{task.id.replace('_', '-')}"
        if task.schedule_type == "daily":
            try:
                hour_text, minute_text = (task.run_at or "").split(":", 1)
                calendar = {"Hour": int(hour_text), "Minute": int(minute_text)}
            except (ValueError, AttributeError):
                raise RuntimeError(f"Daily task {task.id!r} needs run_at=HH:MM") from None
        elif task.schedule_type == "hourly":
            if task.minute_past_hour is None or not 0 <= task.minute_past_hour <= 59:
                raise RuntimeError(f"Hourly task {task.id!r} needs minute_past_hour between 0 and 59")
            calendar = {"Minute": task.minute_past_hour}
        else:
            raise RuntimeError(f"Unsupported launchd schedule type for {task.id!r}: {task.schedule_type}")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", task.id)
        definitions.append(
            (
                label,
                {
                    **common,
                    "Label": label,
                    "ProgramArguments": gated_program_arguments(
                        ["-m", "fantasy_advisor.automation", "--task", task.id],
                        gate=python_gate,
                    ),
                    "RunAtLoad": False,
                    "StartCalendarInterval": calendar,
                    "StandardOutPath": str(LOG_DIR / f"fantasy-{safe_name}.log"),
                    "StandardErrorPath": str(LOG_DIR / f"fantasy-{safe_name}.error.log"),
                },
            )
        )
    return definitions


def plist_path(label: str, *, launch_agents: Path = LAUNCH_AGENTS) -> Path:
    return launch_agents / f"{label}.plist"


def plist_bytes(document: dict[str, Any]) -> bytes:
    with io.BytesIO() as stream:
        plistlib.dump(document, stream, fmt=plistlib.FMT_XML, sort_keys=False)
        return stream.getvalue()


def gated_program_arguments(arguments: list[str], *, gate: Path = PYTHON_GATE) -> list[str]:
    command = "exec " + " ".join(
        shlex.quote(argument) for argument in [str(gate), *arguments]
    )
    return ["/bin/zsh", "-lc", command]


def sync_runtime(repo_root: Path = ROOT, *, runtime_root: Path = RUNTIME_ROOT) -> Path:
    """Copy the runnable project outside macOS's protected Documents folder."""

    if not (repo_root / ".env").exists():
        raise RuntimeError(f"Missing local credentials file: {repo_root / '.env'}")
    source_python = repo_root / ".venv"
    if not source_python.exists():
        raise RuntimeError(f"Missing virtual environment: {source_python}")

    runtime_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime_root.chmod(0o700)
    for relative in ("src", "automation", "docs", "public"):
        shutil.copytree(
            repo_root / relative,
            runtime_root / relative,
            symlinks=True,
            dirs_exist_ok=True,
        )
    source_data = repo_root / "data"
    runtime_data = runtime_root / "data"
    runtime_data.mkdir(parents=True, exist_ok=True)
    seed_runtime_automation_data(source_data, runtime_data)
    for entry in source_data.iterdir():
        if entry.name == "automation":
            continue
        destination = runtime_data / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination)
    for filename in ("league_context.md", "pyproject.toml"):
        shutil.copy2(repo_root / filename, runtime_root / filename)

    runtime_scripts = runtime_root / "scripts"
    runtime_scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repo_root / "scripts" / "run_python_after_startup.sh",
        runtime_scripts / "run_python_after_startup.sh",
    )
    (runtime_scripts / "run_python_after_startup.sh").chmod(0o755)

    runtime_venv = runtime_root / ".venv"
    if runtime_venv.is_symlink() or runtime_venv.exists():
        shutil.rmtree(runtime_venv)
    shutil.copytree(source_python, runtime_venv, symlinks=True)
    for editable_path in runtime_venv.glob("lib/python*/site-packages/__editable__*.pth"):
        editable_path.write_text(f"{runtime_root / 'src'}\n", encoding="utf-8")

    runtime_env = runtime_root / ".env"
    shutil.copy2(repo_root / ".env", runtime_env)
    runtime_env.chmod(0o600)
    return runtime_root


def print_preview(definitions: list[tuple[str, dict[str, Any]]], *, uid: int) -> None:
    for label, document in definitions:
        print(f"# {plist_path(label)}")
        print(plist_bytes(document).decode("utf-8"), end="\n\n")
        print(f"# launchctl bootstrap gui/{uid} {plist_path(label)}\n")


def launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if shutil.which("launchctl") is None:
        raise RuntimeError("launchctl is only available on macOS")
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=check)


def install(definitions: list[tuple[str, dict[str, Any]]], *, uid: int) -> None:
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for label, document in definitions:
        target = plist_path(label)
        temporary = target.with_suffix(".plist.tmp")
        temporary.write_bytes(plist_bytes(document))
        temporary.replace(target)
        launchctl("bootout", f"gui/{uid}", str(target), check=False)
        result = launchctl("bootstrap", f"gui/{uid}", str(target), check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Could not load {target}: {detail or result.returncode}")
        print(f"Installed {label}")


def uninstall(definitions: list[tuple[str, dict[str, Any]]], *, uid: int) -> None:
    for label, _ in definitions:
        target = plist_path(label)
        result = launchctl("bootout", f"gui/{uid}", str(target), check=False)
        if result.returncode and "Could not find service" not in (result.stderr or ""):
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Could not stop {label}: {detail or result.returncode}")
        print(f"Stopped {label}; definition left at {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install fantasy advisor launchd agents")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--dry-run", action="store_true", help="print plist definitions without changing the system")
    choice.add_argument("--install", action="store_true", help="install and load the four launchd agents")
    choice.add_argument("--uninstall", action="store_true", help="stop the four agents; leave plist definitions in place")
    parser.add_argument("--python", type=Path, default=PYTHON, help="Python interpreter for the agents")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 11):
        raise RuntimeError("Use .venv/bin/python (Python 3.11+) to run this installer")
    if args.dry_run:
        definitions = agent_definitions(python=args.python, repo_root=ROOT)
        print_preview(definitions, uid=os.getuid())
        return 0
    if sys.platform != "darwin":
        raise RuntimeError("The launchd installer must run on macOS")
    if not args.python.exists():
        raise RuntimeError(f"Python interpreter not found: {args.python}; create .venv first")
    if args.install:
        from fantasy_advisor.automation import AppConfig

        config = AppConfig.from_environment(repo_root=ROOT)
        config.require_discord()
        config.require_scheduled_discord()
        duplicate_containers = running_fantasy_discord_containers()
        if duplicate_containers:
            names = ", ".join(duplicate_containers)
            raise RuntimeError(
                "Refusing to start a second Fantasy Discord listener while these Docker "
                f"containers are running: {names}. Stop the duplicate listener first."
            )
        runtime_root = sync_runtime(ROOT)
        definitions = agent_definitions(
            python=runtime_root / ".venv" / "bin" / "python",
            repo_root=runtime_root,
            python_gate=runtime_root / "scripts" / "run_python_after_startup.sh",
        )
        install(definitions, uid=os.getuid())
        return 0
    definitions = agent_definitions(python=args.python, repo_root=ROOT)
    uninstall(definitions, uid=os.getuid())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
