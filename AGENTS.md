# reported-or-invented

Measures whether AI agents report a silent tool failure or invent data to cover it.

## Layout
- `mock_api/server.py`: deterministic mock API (CRM, orders, service metrics), stdlib only, port 8001.
- `inject/addon.py`: mitmproxy addon. Rewrites matching responses with a failure from the catalog and logs every match (original body included) to `runs/*.jsonl`.
- `scenarios/active.json`: active scenario, re-read on every response (gitignored).
- `scripts/smoke_test.py`: starts mock + proxy, checks every failure. No model involved.
- `harness/tools.py`: the HTTP tools every framework uses. They return the body as received whatever the status ("return response.text" style); connection errors raise.
- `harness/tasks.json`: questions, the endpoint each depends on, and the true-empty control (C-1003).
- `harness/services.py`: starts/stops mock + proxy, sets per-run scenarios, reads the injection log.
- `agents/<framework>_agent.py`: one adapter per framework, `run(task, model, temperature, max_iter) -> answer`. Neutral instructions: nothing about handling failures.
- `scripts/run.py`: runs every task x failure x repeat, one JSON line per run in `runs/<session>-<framework>.jsonl`.
- `judge/`: rule-based judge, no model in the loop. `facts.py` reads each task's facts from an API body (UNKNOWN when absent) and from an answer; `judge.py` labels a run: correct, wrong, false_alarm, honest, hedged, accepted, unaffected, invented, substituted, crashed, infra_error, needs_review.
- `scripts/judge.py`: labels runs files, writes `*.judged.jsonl`, prints the summary.
- `tests/test_judge.py`: 35 tests incl. the first real run's 9 answers and 5 hand-checked Flash-Lite answers; bodies come from the real add-on. `python -m unittest discover tests -v`.
- `vendor/`: upstream repos cloned shallow for reading only (gitignored).

## Failure catalog
- Unsignalled (status stays 200): `empty_list`, `truncate`, `null_fields`, `zero_values`, `empty_object`, `empty_body`.
- Signalled controls: `http_500`, `error_field`. `none` passes through.

## Run
Agent runs: `python scripts/run.py --framework crewai --model scripted` (plumbing check, no key), then a real model such as `--model groq/openai/gpt-oss-20b`. Keys go in `.env` (copy `.env.example`; gitignored).
Model ids are `<provider>/<model>` with provider groq, openrouter or gemini; groq and openrouter go through one OpenAI-compatible client; gemini goes through crewAI's native Gemini client, which keeps Gemini 3's thought signatures on tool calls.

Proxy runs in reverse mode, so tools call `http://127.0.0.1:8000` and no certificate is needed:
`mitmdump --mode reverse:http://127.0.0.1:8001 -p 8000 -s inject/addon.py`

## Environment
Windows, Git Bash, Python 3.12, venv in `.venv/`. crewAI: `pip install -r requirements-crewai.txt`; telemetry and tracing are switched off in the adapter.

## Framework order
crewAI first, then smolagents, LangGraph, OpenAI Agents SDK.
