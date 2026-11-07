# Reported or invented?

Measures how often AI agents invent data when a tool fails silently, instead of reporting the failure.

**How it works**
- `mock_api/`: a local API, so every run can be repeated exactly
- `inject/`: a mitmproxy addon that changes the HTTP responses tools receive (empty body, error page, fill values, timeouts), so it works with any agent framework without adapter code
- `agents/`: agent runners (crewAI first; smolagents, LangGraph and the OpenAI Agents SDK next)
- `judge/`: rule-based labels for each run: failure reported, data invented, or other
- `harness/`, `scripts/`, `tests/`: tasks, tools, run and judge scripts, tests

**Status (Nov 2026)**: injection, mock API and smoke test pass end to end; crewAI dry run completed 28 runs with 0 errors. No real-model results yet.

Run notes: `CLAUDE.md`.

Author: Houssain El Marouni
