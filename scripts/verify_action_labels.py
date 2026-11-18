"""Check that re-judging the 12 action batch sets changes exactly the listed labels.

  python scripts/verify_action_labels.py

Reads experiments/action-tier/labels-before.tsv (the labels the batch was first judged
with) and corrections.tsv (file, run_id, before, after, reason: the labels that are meant
to change, each with a reason). Copies the 12 raw run
files to a temporary directory, judges them there with the current code and compares:
a run in corrections.tsv must get its "after" label, every other run must keep its
"before" label. Nothing is written to runs/.

Exit 0 and "PASS: ..." when they agree, otherwise exit 1 and list every mismatch.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIER = ROOT / "experiments" / "action-tier"
RUNS = ROOT / "runs"
CORRECTION_COLUMNS = ["file", "run_id", "before", "after", "reason"]


def read_tsv(path):
    # QUOTE_NONE: the reason column is free text and may contain quote characters.
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))
    return rows[0], rows[1:]


def main():
    sys.stdout.reconfigure(errors="replace")
    _, before_rows = read_tsv(TIER / "labels-before.tsv")
    correction_header, correction_rows = read_tsv(TIER / "corrections.tsv")

    before = {(f, rid): label for f, rid, label in before_rows}
    problems = []
    if correction_header != CORRECTION_COLUMNS:
        problems.append(("corrections.tsv", "-", ",".join(CORRECTION_COLUMNS),
                         ",".join(correction_header), "header"))
    corrections = {}
    for row in correction_rows:
        if len(row) != len(CORRECTION_COLUMNS) or not row[4].strip():
            problems.append((row[0], row[1] if len(row) > 1 else "-",
                             "5 columns with a reason", f"{len(row)} columns", "\t".join(row)))
            continue
        corrections[(row[0], row[1])] = (row[2], row[3])

    for key, (was, now) in corrections.items():
        if key not in before:
            problems.append((*key, "run listed in corrections.tsv is not in labels-before.tsv", "-", ""))
        elif before[key] != was:
            problems.append((*key, f"corrections.tsv says before={was}", before[key], ""))
    expected = {key: corrections[key][1] if key in corrections else label
                for key, label in before.items()}

    files = sorted({f for f, _ in before})
    raw_names = [f.replace(".judged.jsonl", ".jsonl") for f in files]
    got, answers = {}, {}
    with tempfile.TemporaryDirectory(prefix="roi-verify-") as tmp:
        tmp = Path(tmp)
        for name in raw_names:
            shutil.copyfile(RUNS / name, tmp / name)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "judge.py"), *[str(tmp / n) for n in raw_names]],
            capture_output=True, env=env, cwd=str(ROOT))
        if done.returncode:
            print("scripts/judge.py failed:")
            print(done.stderr.decode("utf-8", "replace")[-2000:])
            return 1
        for name in raw_names:
            judged = name.replace(".jsonl", ".judged.jsonl")
            for line in (tmp / judged).read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                key = (judged, record["run_id"])
                got[key] = record["judge"]["label"]
                answers[key] = record.get("answer") or ""

    for key, want in expected.items():
        if key not in got:
            problems.append((*key, want, "<missing>", ""))
        elif got[key] != want:
            problems.append((*key, want, got[key], answers[key]))
    for key in got.keys() - expected.keys():
        problems.append((*key, "<not in labels-before.tsv>", got[key], answers[key]))

    if problems:
        print(f"FAIL: {len(problems)} mismatches")
        for f, rid, want, have, answer in problems:
            print(f"{f}\t{rid}\texpected={want}\tgot={have}\n    {answer[:200]!r}")
        return 1
    print(f"PASS: {len(corrections)} changed as listed, {len(before) - len(corrections)} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
