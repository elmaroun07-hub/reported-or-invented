#!/usr/bin/env bash
# Run manually from Git Bash. Prepared only; not launched by action-tier setup.
# 4 frameworks x 3 arms x 84 runs = 1,008 runs.
set -uo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) || exit 1
cd -- "$ROOT" || exit 1

python_for() {
    case "$1" in
        crewai) printf '%s\n' './.venv/Scripts/python' ;;
        langgraph|adk) printf '%s\n' "$HOME/roi-claude/.venv/Scripts/python" ;;
        openai_agents) printf '%s\n' "$HOME/roi-codex/.venv/Scripts/python" ;;
    esac
}

preflight() {
    local fw python
    for fw in crewai langgraph adk openai_agents; do
        python=$(python_for "$fw")
        if [[ ! -x "$python" && ! -x "$python.exe" ]]; then
            printf 'PREFLIGHT FAILED: %s Python not found: %s\n' "$fw" "$python" >&2
            return 1
        fi
        "$python" -B - "$fw" <<'PY' || return 1
import importlib
import sys
from importlib.metadata import version

framework = sys.argv[1]
try:
    # Import this repo's adapter: it imports the framework and handles the
    # local agents package's name collision with the OpenAI Agents SDK.
    adapter = importlib.import_module(f"agents.{framework}_agent")
    import mitmproxy
    print(f"OK {framework} {adapter.VERSION}; mitmproxy {version('mitmproxy')}; python={sys.executable}")
except Exception as exc:
    print(f"PREFLIGHT FAILED: {framework} with {sys.executable}: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)
PY
    done
    ./.venv/Scripts/python -B - <<'PY' || return 1
import socket
import sys

sockets = []
try:
    for port in (8000, 8001):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockets.append(listener)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
    print("OK ports 8000 and 8001 are free on 127.0.0.1")
except OSError as exc:
    print(f"PREFLIGHT FAILED: port {port} is unavailable: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    for listener in sockets:
        listener.close()
PY
    echo 'PREFLIGHT PASSED'
}

if [[ "${1:-}" == "--preflight-only" ]]; then
    preflight
    exit $?
fi

mkdir -p runs || exit 1
exec > >(tee -a "$ROOT/runs/action-console.log") 2>&1
export PYTHONUNBUFFERED=1
source "$ROOT/.venv/Scripts/activate" || exit 1
printf 'Action suite started %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
preflight || exit 1

# Keep the execution-state request on a live PowerShell thread for the batch.
# The marker lets EXIT/INT/TERM cleanup ask that thread to release it normally.
awake_marker=$(mktemp "$ROOT/runs/.action-awake.XXXXXX") || exit 1
awake_pid=
cleanup() {
    rm -f -- "$awake_marker"
    if [[ -n "$awake_pid" ]]; then
        wait "$awake_pid" || true
    fi
    rm -f -- "$awake_marker.ready"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export ROI_ACTION_AWAKE_FILE
ROI_ACTION_AWAKE_FILE=$(cygpath -w "$awake_marker") || exit 1
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -Command '
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ActionAwake {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
try {
    $previous = [ActionAwake]::SetThreadExecutionState([uint32]2147483649)
    if ($previous -eq 0) { throw "SetThreadExecutionState failed" }
    [System.IO.File]::WriteAllText($env:ROI_ACTION_AWAKE_FILE + ".ready", "ready")
    while (Test-Path -LiteralPath $env:ROI_ACTION_AWAKE_FILE) {
        Start-Sleep -Seconds 1
    }
} finally {
    [void][ActionAwake]::SetThreadExecutionState([uint32]2147483648)
}
' &
awake_pid=$!
for ((attempt = 0; attempt < 100; attempt++)); do
    [[ -f "$awake_marker.ready" ]] && break
    kill -0 "$awake_pid" 2>/dev/null || break
    sleep 0.1
done
if [[ ! -f "$awake_marker.ready" ]]; then
    echo 'Could not establish the Windows keep-awake request; no sets started.'
    exit 1
fi

failed_sets=0
for fw in crewai langgraph adk openai_agents; do
    for v in baseline prompt flag; do
        printf '\n== Starting %s / %s ==\n' "$fw" "$v"
        set_log=$(mktemp "$ROOT/runs/action-${fw}-${v}.XXXXXX.log") || exit 1
        "$(python_for "$fw")" scripts/run.py --framework "$fw" --model groq/openai/gpt-oss-20b \
            --suite action --max-iter 8 --repeats 3 --pause 4 --variant "$v" 2>&1 | tee "$set_log"
        run_status=${PIPESTATUS[0]}

        # Use this invocation's announced filename, never a stale newest file.
        # pathlib prints backslashes on Windows; normalize for Git Bash.
        run_file=$(awk '/^[0-9]+ runs -> / {
            sub(/^[0-9]+ runs -> /, ""); sub(/\r$/, ""); gsub(/\\/, "/"); print; exit
        }' "$set_log")
        judge_status=1
        suffix="-$v"
        [[ "$v" == baseline ]] && suffix=
        if [[ "$run_file" == runs/*-"$fw"-action"$suffix".jsonl && -s "$run_file" ]]; then
            ./.venv/Scripts/python scripts/judge.py "$run_file"
            judge_status=$?
        else
            echo "No nonempty run file from this set; skipping its judge."
        fi
        printf 'Set status: runner=%d judge=%d\n' "$run_status" "$judge_status"
        if ((run_status != 0 || judge_status != 0)); then
            failed_sets=$((failed_sets + 1))
            echo 'Set failed; continuing with the remaining sets.'
        fi
    done
done

cleanup
trap - EXIT
printf '\nFailed sets: %d\n' "$failed_sets"
printf 'ALL DONE %s\n' "$(date '+%H:%M')"
((failed_sets == 0))
