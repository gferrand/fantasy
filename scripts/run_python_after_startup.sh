#!/bin/zsh

# launchd can start a user agent while macOS is locked before the Python
# runtime is able to initialize. Keep the native shell process alive and retry
# a tiny Python startup probe until the session is usable, then hand off to the
# requested module. This applies equally to the gateway and scheduled tasks.

set -u

script_dir="${0:A:h}"
repo_root="${script_dir:h}"
python_bin="${FANTASY_PYTHON:-$repo_root/.venv/bin/python}"

if [[ ! -x "$python_bin" ]]; then
  print -u2 "Python interpreter not found: $python_bin"
  exit 1
fi

if (( $# == 0 )); then
  print -u2 "Usage: run_python_after_startup.sh <python arguments>"
  exit 2
fi

probe_pid=""
cleanup() {
  if [[ -n "$probe_pid" ]] && kill -0 "$probe_pid" 2>/dev/null; then
    kill "$probe_pid" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

while true; do
  "$python_bin" -c 'print("python-ready", flush=True)' >/dev/null 2>&1 &
  probe_pid=$!
  probe_status=124
  probe_finished=0

  for _ in {1..60}; do
    if ! kill -0 "$probe_pid" 2>/dev/null; then
      wait "$probe_pid"
      probe_status=$?
      probe_finished=1
      break
    fi
    sleep 1
  done

  if (( ! probe_finished )); then
    kill "$probe_pid" 2>/dev/null || true
    wait "$probe_pid" 2>/dev/null || true
  fi
  probe_pid=""

  if (( probe_status == 0 )); then
    break
  fi
  sleep 30
done

trap - INT TERM EXIT
exec "$python_bin" "$@"
