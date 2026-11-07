# Reported or invented?

Measures how often AI agents invent data when a tool fails silently, instead of reporting the failure.

**How it works**
- `mock_api/`: a local API, so every run can be repeated exactly
- `inject/`: a mitmproxy addon that rewrites the HTTP responses tools receive: empty list, truncated body, null fields, zero values, empty object, empty body (status stays 200), plus HTTP 500 and an error field as signalled controls. Works with any agent framework without adapter code
- `agents/`: agent runners (crewAI first; smolagents, LangGraph and the OpenAI Agents SDK next)
- `judge/`: rule-based, no model in the loop; labels each run as correct, wrong, false_alarm, honest, hedged, accepted, invented, crashed, infra_error or needs_review
- `harness/`, `scripts/`, `tests/`: tasks, tools, run and judge scripts, tests

**Status (Nov 2026)**: injection, mock API and smoke test pass end to end; crewAI dry run: 28 runs, 0 errors; the first real-model run (9 answers) is labelled by the judge and kept as test cases (23 tests). The full experiment hasn't run yet.

Run notes: `CLAUDE.md`. Copy `.env.example` to `.env` for API keys.

Author: Houssain El Marouni
