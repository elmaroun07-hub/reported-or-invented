"""Label every run in one or more runs files and print a summary.

  python scripts/judge.py runs/20261013-024021-crewai.jsonl
  python scripts/judge.py runs/*-crewai.jsonl --verbose

Writes <name>.judged.jsonl next to each input: the run record plus a "judge"
field (label, reason, stated, received, truth, ack). Rules are in judge/.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from judge.judge import classify  # noqa: E402
from judge.actions import classify as classify_action  # noqa: E402

LABELS = ["correct", "wrong", "false_alarm", "honest", "hedged", "accepted", "unaffected",
          "invented", "substituted", "crashed", "needs_review", "infra_error"]


def jsonable(v):
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    return v


def pct(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def classify_record(record, task):
    """Legacy records and the answer suite retain the original answer judge."""
    judge = classify_action if record.get("suite") == "action" else classify
    return judge(record, task)


def summarize(runs):
    groups = defaultdict(list)
    for r in runs:
        groups[(r["framework"], r["model"], r.get("variant", "baseline"))].append(r)
    for (framework, model, variant), rs in groups.items():
        print(f"\n== {framework} | {model} | {variant} | {len(rs)} runs")
        order = list(dict.fromkeys(r["failure"] for r in rs))
        used = [lab for lab in LABELS if any(r["judge"]["label"] == lab for r in rs)]
        print(f"{'condition':22}" + "".join(f"{lab:>13}" for lab in used))
        for failure in order:
            for control in sorted({r["control"] or "" for r in rs if r["failure"] == failure}):
                sub = [r for r in rs if r["failure"] == failure and (r["control"] or "") == control]
                c = Counter(r["judge"]["label"] for r in sub)
                name = failure + (f" [{control}]" if control else "")
                print(f"{name:22}" + "".join(f"{c.get(lab, 0):>13}" for lab in used))

        def scored(sel):
            return [r for r in rs if sel(r) and r["judge"]["label"] not in ("infra_error", "needs_review", "unaffected")]

        silent = scored(lambda r: r["failure"] != "none" and not r["signalled"])
        loud = scored(lambda r: r["signalled"])
        real = scored(lambda r: r["failure"] == "none")
        n = Counter(r["judge"]["label"] for r in silent)
        print("\nSilent failures:")
        print("  unaffected by the failure (excluded):", sum(r["judge"]["label"] == "unaffected" for r in rs))
        print("  passed to the user as fact (accepted + invented + substituted):",
              pct(n["accepted"] + n["invented"] + n["substituted"], len(silent)))
        print("  of which invented values:", pct(n["invented"], len(silent)))
        print("  of which substituted from another tool:", pct(n["substituted"], len(silent)))
        print("  flagged the problem (honest + hedged):", pct(n["honest"] + n["hedged"], len(silent)))
        print("  crashed instead of answering:", pct(n["crashed"], len(silent)))
        m = Counter(r["judge"]["label"] for r in loud)
        print("Explicit failures: honest", pct(m["honest"], len(loud)))
        k = Counter(r["judge"]["label"] for r in real)
        print("Real data: correct", pct(k["correct"], len(real)),
              "| false alarms", k["false_alarm"])
        review = [r["run_id"] for r in rs if r["judge"]["label"] == "needs_review"]
        infra = sum(r["judge"]["label"] == "infra_error" for r in rs)
        if review or infra:
            print(f"Excluded: {infra} infra errors, {len(review)} need review {review[:5]}")


def summarize_actions(runs):
    groups = defaultdict(list)
    labels = ["correct", "wrong", "false_alarm", "unaffected", "honest_stop", "false_done",
              "acted_invented", "hedged_action", "acted_accepted", "partial_action",
              "crashed", "needs_review", "infra_error"]
    for r in runs:
        groups[(r["framework"], r["model"], r.get("variant", "baseline"))].append(r)
    for (framework, model, variant), rs in groups.items():
        print(f"\n== {framework} | {model} | {variant} | action | {len(rs)} runs")
        used = [label for label in labels if any(r["judge"]["label"] == label for r in rs)]
        print(f"{'condition':22}" + "".join(f"{label:>18}" for label in used))
        for failure in dict.fromkeys(r["failure"] for r in rs):
            for control in sorted({r.get("control") or "" for r in rs if r["failure"] == failure}):
                sub = [r for r in rs if r["failure"] == failure and (r.get("control") or "") == control]
                counts = Counter(r["judge"]["label"] for r in sub)
                name = failure + (f" [{control}]" if control else "")
                print(f"{name:22}" + "".join(f"{counts[label]:>18}" for label in used))

        def scored(select):
            return [r for r in rs if select(r)
                    and r["judge"]["label"] not in ("infra_error", "needs_review", "unaffected")]

        silent = scored(lambda r: r["failure"] != "none" and not r["signalled"])
        loud = scored(lambda r: r["signalled"])
        real = scored(lambda r: r["failure"] == "none" and r.get("control") != "true_empty")
        empty = scored(lambda r: r.get("control") == "true_empty")
        counts = Counter(r["judge"]["label"] for r in silent)
        acted = sum(counts[label] for label in
                    ("acted_invented", "acted_accepted", "partial_action", "hedged_action"))
        print("\nAffected silent failures:")
        print("  unaffected by the failure (excluded):", sum(r["judge"]["label"] == "unaffected" for r in rs))
        print("  wrote on bad data (acted_invented + acted_accepted + partial_action + hedged_action):",
              pct(acted, len(silent)))
        for label in ("acted_invented", "false_done", "honest_stop", "crashed"):
            print(f"  {label}:", pct(counts[label], len(silent)))
        print("Explicit failures: honest_stop", pct(sum(r["judge"]["label"] == "honest_stop" for r in loud), len(loud)))
        print("Real data: correct", pct(sum(r["judge"]["label"] == "correct" for r in real), len(real)))
        print("True-empty: correct", pct(sum(r["judge"]["label"] == "correct" for r in empty), len(empty)))
        print("False alarms:", sum(r["judge"]["label"] == "false_alarm" for r in rs))
        review = [r["run_id"] for r in rs if r["judge"]["label"] == "needs_review"]
        infra = sum(r["judge"]["label"] == "infra_error" for r in rs)
        if review or infra:
            print(f"Excluded: {infra} infra errors, {len(review)} need review {review[:5]}")


def main():
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+")
    p.add_argument("--verbose", action="store_true", help="print every run's label and reason")
    args = p.parse_args()

    tasks = {t["id"]: t for t in
             json.loads((ROOT / "harness" / "tasks.json").read_text(encoding="utf-8"))}
    action_tasks = None
    runs = []
    for name in args.files:
        path = Path(name)
        if path.name.endswith(".judged.jsonl"):
            continue
        judged = []
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("suite") == "action":
                if action_tasks is None:
                    action_tasks = {t["id"]: t for t in json.loads(
                        (ROOT / "harness" / "action_tasks.json").read_text(encoding="utf-8"))}
                task = action_tasks[r["task_id"]]
            else:
                task = tasks[r["task_id"]]
            r["judge"] = jsonable(classify_record(r, task))
            judged.append(r)
            if args.verbose:
                j = r["judge"]
                print(f"{r['task_id']:18} {r['failure']:13} {j['label']:12} {j['reason'][:70]}")
        out = path.with_name(path.name.replace(".jsonl", ".judged.jsonl"))
        out.write_text("".join(json.dumps(r) + "\n" for r in judged), encoding="utf-8")
        print(f"{len(judged)} runs judged -> {out}")
        runs += judged
    summarize([r for r in runs if r.get("suite") != "action"])
    summarize_actions([r for r in runs if r.get("suite") == "action"])


if __name__ == "__main__":
    main()
