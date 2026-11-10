"""Run an agent framework against the mock API under every failure condition.

  python scripts/run.py --framework crewai --model scripted          # plumbing, no key
  python scripts/run.py --framework crewai --model groq/openai/gpt-oss-20b

Each agent run gets its own scenario: the failure is applied to the task's
endpoint, and every other call passes through but is still logged. One JSON
line per run goes to runs/<session>-<framework>.jsonl, with the answer and the
exact responses the tools received.
"""
import argparse
import importlib
import importlib.util
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.env import load_dotenv  # noqa: E402
from harness.services import Services  # noqa: E402


def failure_catalog():
    spec = importlib.util.spec_from_file_location("roi_addon", ROOT / "inject" / "addon.py")
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    return addon.FAILURES, set(addon.SIGNALLED)


def main():
    sys.stdout.reconfigure(errors="replace")
    failures_all, signalled = failure_catalog()
    p = argparse.ArgumentParser()
    p.add_argument("--framework", required=True, choices=["crewai"])
    p.add_argument("--model", required=True)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    p.add_argument("--failures", default="", help=f"comma-separated, from {failures_all}")
    p.add_argument("--max-iter", type=int, default=6)
    p.add_argument("--pause", type=float, default=2.0, help="seconds between runs (rate limits)")
    args = p.parse_args()

    load_dotenv(ROOT / ".env")
    adapter = importlib.import_module(f"agents.{args.framework}_agent")

    tasks = json.loads((ROOT / "harness" / "tasks.json").read_text(encoding="utf-8"))
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in wanted]
    failures = args.failures.split(",") if args.failures else failures_all
    unknown = set(failures) - set(failures_all)
    if unknown:
        sys.exit(f"unknown failures: {sorted(unknown)}")

    session = time.strftime("%Y%m%d-%H%M%S")
    runs_dir = ROOT / "runs"
    out_path = runs_dir / f"{session}-{args.framework}.jsonl"
    plan = [(t, f, r) for t in tasks for f in t.get("failures", failures)
            for r in range(args.repeats)]
    print(f"{len(plan)} runs -> {out_path.relative_to(ROOT)}")

    errors = 0
    with Services(runs_dir / f"{session}-scenario.json",
                  runs_dir / f"{session}-injections.jsonl") as svc, \
            out_path.open("a", encoding="utf-8") as out:
        for i, (task, failure, rep) in enumerate(plan, 1):
            run_id = f"{task['id']}.{failure}.r{rep}.{uuid.uuid4().hex[:6]}"
            svc.set_scenario(run_id, [
                {"method": "GET", "path": task["endpoint"], "failure": failure},
                {"method": "*", "path": "*", "failure": "none"},
            ])
            started = time.time()
            answer, error = None, None
            try:
                answer = adapter.run(task, args.model, args.temperature, args.max_iter)
            except Exception as e:  # recorded, never hidden; the judge sorts crash vs infra fault
                error = f"{type(e).__name__}: {e}"
                errors += 1
            calls = svc.records(run_id)
            record = {
                "run_id": run_id,
                "session": session,
                "framework": args.framework,
                "framework_version": adapter.VERSION,
                "model": args.model,
                "temperature": args.temperature,
                "task_id": task["id"],
                "control": task.get("control"),
                "question": task["question"],
                "failure": failure,
                "signalled": failure in signalled,
                "repeat": rep,
                "answer": answer,
                "error": error,
                "duration_s": round(time.time() - started, 2),
                "called_target": any(c["rule_path"] == task["endpoint"] for c in calls),
                "tool_calls": [{k: c[k] for k in ("url", "failure", "outcome",
                                                  "sent_status", "sent_body")}
                               for c in calls],
            }
            out.write(json.dumps(record) + "\n")
            out.flush()
            status = "ERROR " + error[:60] if error else (answer or "")[:60].replace("\n", " ")
            print(f"[{i}/{len(plan)}] {task['id']:18} {failure:13} r{rep} "
                  f"calls={len(calls)} {record['duration_s']:5.1f}s  {status}")
            if i < len(plan):
                time.sleep(args.pause)

    print(f"\ndone: {len(plan)} runs, {errors} errored -> {out_path.relative_to(ROOT)}")
    return 1 if errors == len(plan) else 0


if __name__ == "__main__":
    sys.exit(main())
