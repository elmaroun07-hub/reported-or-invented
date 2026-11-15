#!/usr/bin/env bash
# Run manually from Git Bash. This script is not launched by sprint setup.
set -uo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) || exit 1
cd -- "$ROOT" || exit 1
mkdir -p runs || exit 1
exec > >(tee -a "$ROOT/runs/sprint-console.log") 2>&1
export PYTHONUNBUFFERED=1
source "$ROOT/.venv/Scripts/activate" || exit 1
printf 'Sprint started %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"

# Keep the execution-state request on a live PowerShell thread for the batch.
# The marker lets EXIT/INT/TERM cleanup ask that thread to release it normally.
awake_marker=$(mktemp "$ROOT/runs/.sprint-awake.XXXXXX") || exit 1
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
export ROI_SPRINT_AWAKE_FILE
ROI_SPRINT_AWAKE_FILE=$(cygpath -w "$awake_marker") || exit 1
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -Command '
$ErrorActionPreference = "Stop"
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class SprintAwake {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
}
"@
try {
    $previous = [SprintAwake]::SetThreadExecutionState([uint32]2147483649)
    if ($previous -eq 0) { throw "SetThreadExecutionState failed" }
    [System.IO.File]::WriteAllText($env:ROI_SPRINT_AWAKE_FILE + ".ready", "ready")
    while (Test-Path -LiteralPath $env:ROI_SPRINT_AWAKE_FILE) {
        Start-Sleep -Seconds 1
    }
} finally {
    [void][SprintAwake]::SetThreadExecutionState([uint32]2147483648)
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
for fw in crewai langgraph openai_agents adk; do
    for v in prompt flag; do
        printf '\n== Starting %s / %s ==\n' "$fw" "$v"
        set_log=$(mktemp "$ROOT/runs/sprint-${fw}-${v}.XXXXXX.log") || exit 1
        python scripts/run.py --framework "$fw" --model groq/openai/gpt-oss-20b \
            --repeats 3 --pause 4 --variant "$v" 2>&1 | tee "$set_log"
        run_status=${PIPESTATUS[0]}

        # Use this invocation's announced filename, never a stale newest file.
        # pathlib prints backslashes on Windows; normalize for Git Bash.
        run_file=$(awk '/^[0-9]+ runs -> / {
            sub(/^[0-9]+ runs -> /, ""); sub(/\r$/, ""); gsub(/\\/, "/"); print; exit
        }' "$set_log")
        judge_status=1
        if [[ "$run_file" == runs/*-"$fw"-"$v".jsonl && -s "$run_file" ]]; then
            python scripts/judge.py "$run_file"
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
