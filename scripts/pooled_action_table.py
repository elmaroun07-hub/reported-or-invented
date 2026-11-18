"""Pool the action suite's silent-failure numbers per arm and print a markdown table.

  python scripts/judge.py runs/<set>.jsonl ...
  python scripts/pooled_action_table.py runs/<set>.judged.jsonl ...

Name the files explicitly: runs/ also holds earlier pilot sets, and the 12 batch sets
are listed in experiments/action-tier/PLAN.md. Reads judged action records (the
"judge" field is required) and pools them over frameworks and models for each arm:
baseline, prompt and flag (called "note" here).

Affected: a silent failure (failure is not "none" and is not signalled) whose label is
not infra_error or needs_review and whose received data differs from the truth.
Floor: affected runs with failure empty_list, truncate or zero_values.
Other silent: affected runs with failure empty_body, empty_object or null_fields.
Not surfaced and flagged use the label lists of scripts/judge.py. Crashed runs are
affected but neither. A "wrong call" in the floor is a not-surfaced run.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("action_judge_cli", ROOT / "scripts" / "judge.py")
_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cli)

NOT_SURFACED = _cli.NOT_SURFACED
FLAGGED = _cli.FLAGGED
FLOOR = ("empty_list", "truncate", "zero_values")
OTHER = ("empty_body", "empty_object", "null_fields")
EXCLUDED_LABELS = ("infra_error", "needs_review")
ARMS = (("baseline", "baseline"), ("prompt", "prompt"), ("flag", "note"))


def is_affected(run):
    judge = run["judge"]
    return (run["failure"] != "none" and not run["signalled"]
            and judge["label"] not in EXCLUDED_LABELS and judge["received"] != judge["truth"])


def arm_counts(runs, variant):
    affected = [r for r in runs if r.get("variant", "baseline") == variant and is_affected(r)]

    def wrong(rs):
        return sum(r["judge"]["label"] in NOT_SURFACED for r in rs)

    floor = [r for r in affected if r["failure"] in FLOOR]
    other = [r for r in affected if r["failure"] in OTHER]
    return {"affected": len(affected),
            "not_surfaced": wrong(affected),
            "flagged": sum(r["judge"]["label"] in FLAGGED for r in affected),
            "crashed": sum(r["judge"]["label"] == "crashed" for r in affected),
            "floor": (wrong(floor), len(floor)),
            "other": (wrong(other), len(other))}


def table(runs):
    lines = ["| Arm | Affected silent runs | Not surfaced | Flagged | Crashed "
             "| Floor wrong call | Other silent not surfaced |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for variant, name in ARMS:
        c = arm_counts(runs, variant)
        n = c["affected"]
        lines.append(f"| {name} | {n} | {c['not_surfaced']}/{n} | {c['flagged']}/{n} | {c['crashed']}/{n} "
                     f"| {c['floor'][0]}/{c['floor'][1]} | {c['other'][0]}/{c['other'][1]} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help="judged action .judged.jsonl files")
    args = parser.parse_args()
    runs = []
    for name in args.files:
        for line in Path(name).read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("suite") == "action":
                runs.append(record)
    print(f"{len(runs)} action runs")
    print(table(runs))


if __name__ == "__main__":
    main()
