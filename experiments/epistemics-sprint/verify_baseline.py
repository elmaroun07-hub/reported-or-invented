"""Rejudge copies of every saved JSONL file; diff labels without writing results/."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "runs" / "sprint-baseline-check"


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sources = sorted((ROOT / "results").glob("*.jsonl"))
    before = []
    copies = []
    for index, source in enumerate(sources):
        saved = source if source.name.endswith(".judged.jsonl") else source.with_suffix(".judged.jsonl")
        labels = {r["run_id"]: r["judge"]["label"] for r in records(saved)}
        rows = records(source)
        before.extend(f"{source.name}\t{r['run_id']}\t{labels[r['run_id']]}\n" for r in rows)
        copy = OUTPUT / f"{index}-{source.name.replace('.judged', '')}"
        copy.write_bytes(source.read_bytes())
        copies.append(copy)
    with (OUTPUT / "rejudge-console.txt").open("w", encoding="utf-8") as console:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "judge.py"), *map(str, copies)],
                       cwd=ROOT, stdout=console, stderr=subprocess.STDOUT, check=True)
    after = []
    for source, copy in zip(sources, copies):
        after.extend(f"{source.name}\t{r['run_id']}\t{r['judge']['label']}\n"
                     for r in records(copy.with_suffix(".judged.jsonl")))
    for name, lines in (("labels-before.tsv", before), ("labels-after.tsv", after)):
        (OUTPUT / name).write_text("".join(lines), encoding="utf-8", newline="\n")
    diff = subprocess.run(["git", "-c", "core.autocrlf=false", "diff", "--no-index", "--exit-code",
                           str(OUTPUT / "labels-before.tsv"), str(OUTPUT / "labels-after.tsv")],
                          cwd=ROOT, capture_output=True, text=True)
    (OUTPUT / "labels.diff").write_text(diff.stdout + diff.stderr, encoding="utf-8")
    print(f"{len(sources)} files; {len(before)} label comparisons; diff exit {diff.returncode}")
    print(diff.stdout + diff.stderr, end="")
    return diff.returncode


if __name__ == "__main__":
    sys.exit(main())
