# Sprint implementation verification

15 November 2026. Work started from the clean, fast-forwarded `main` at
`bc6e98a3a22e9580ebe67fac81dcd33e12a7f27f`. Local tag: `pre-sprint`.
Implementation branch: `sprint/epistemics`. No push performed.

## Tests and compatibility

- Before implementation: all 57 existing judge tests passed.
- Red first: the 22 new variant tests exposed absent flags, prompt sentences,
  CLI options, metadata and variant-separated summaries. Expected failures:
  20 failing assertions/subtests and 2 argparse errors for the missing option.
- Final `python -m unittest discover tests -v`: **79 tests passed**, exit 0.
  This includes all original 57 judge tests and 22 variant tests.
- Baseline and flag instruction expressions match the original strings in all
  four adapters. The exact new sentence appears only in prompt. These expression
  checks do not import the optional SDKs and do not claim runtime verification
  of the three uninstalled frameworks.
- Flag tests cover empty and whitespace bodies, invalid JSON/plain text, empty
  lists/objects, nested/root nulls, JSON paths, real API fixtures, zero values,
  shortened lists, genuine empty orders, HTTP errors and connection errors.
- Runner tests check environment propagation, filenames, records, unchanged task
  plan, raw versus returned tool bodies and summary grouping.
- `git diff --check`: exit 0 using the repository's normal line-ending settings.
- `git diff --exit-code bc6e98a -- results judge requirements.txt requirements-crewai.txt requirements-langgraph.txt requirements-adk.txt requirements-openai_agents.txt`:
  no output, exit 0. Saved results, judge rules and requirements are unchanged.

## Label preservation: diff proof

Ran `python experiments/epistemics-sprint/verify_baseline.py`. It copies every
saved JSONL into `runs/sprint-baseline-check/`, invokes `scripts/judge.py` on
those copies, then compares each row's run ID and new label to the committed
label. No outputs are written to `results/`.

```text
8 files; 672 label comparisons; diff exit 0
```

The eight inputs comprise five judged sets and three raw counterparts; thus
some comparisons repeat the same runs. This checks all 420 distinct saved runs,
including the out-of-experiment Flash-Lite set.

```sh
git -c core.autocrlf=false diff --no-index --exit-code runs/sprint-baseline-check/labels-before.tsv runs/sprint-baseline-check/labels-after.tsv
```

Result: no output, exit 0. `labels.diff` is **0 bytes**. Each label snapshot is
56,480 bytes, with identical SHA-256:

```text
d92c021240533b3e36bcff9c65e77de8532a2dd34844222a1db5bc423b9d5f6c
```

## Pilot and batch script

The [plan](PLAN.md) was saved before either pilot. The [pilot transcript](PILOT.md)
contains every answer, source run IDs, raw-file hashes and one complete flagged
tool output. Four prompt and four flag runs completed with no recorded errors;
all eight called the target and used temperature 0. All 14 proxied tool outputs
match the recorded deterministic `returned_body` transformation.

`scripts/sprint_runs.sh` has LF line endings, enforced by `.gitattributes`.
Git Bash `bash -n scripts/sprint_runs.sh` passed. Parsing the embedded PowerShell
with `System.Management.Automation.Language.Parser` returned no errors.
The script has **not been started**: no full-batch runs or runtime keep-awake
checks were performed. It activates the existing `.venv`, uses the requested
framework/arm order, captures each invocation's own filename, judges even a
partial run file, continues after a failed set, logs unbuffered console output,
and releases its hidden background PowerShell keep-awake request on exit.

## Issues and limits

- The current `.venv` contains crewAI 1.15.27 and mitmproxy 12.2.3, but lacks
  LangGraph, Google ADK and OpenAI Agents SDK package metadata. Their runtime
  adapters were not exercised; their sets will fail in this environment until
  those dependencies are available. No packages or requirements were changed.
- Git writes and the Git Bash syntax check required sandbox escalation. Initial
  sandbox attempts were denied; approved retries succeeded. The real pilots used
  approved network access. One shell quoting error in a verification command was
  corrected by moving that check into a temporary Python file. An inspection
  command that disabled Git's normal CRLF conversion produced spurious whole-file
  whitespace warnings; the normal repository check passed without file changes.
- Pilot console previews misrendered some Unicode characters; the JSONL records
  and transcript preserve the exact Unicode answers.
- The flag did not prevent invented zero orders in either affected pilot case.
  This is an observed experimental result, not a reason to alter the fixed arm
  or judge. Eight runs do not establish a general effect.
- `.env` was never inspected or printed. Only the existing runner loaded it for
  the authorized API calls. Raw pilot and verification artifacts remain local
  under ignored `runs/`.
