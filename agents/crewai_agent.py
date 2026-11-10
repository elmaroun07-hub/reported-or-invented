"""crewAI adapter: one agent, one task, the shared HTTP tools.

The agent's instructions are neutral on purpose: nothing tells it how to treat
a failed or empty tool result, so a run measures the framework + model default,
not a prompt fix.

Models are given as <provider>/<model>. Every provider goes through crewAI's
OpenAI-compatible client with an explicit base URL, so all models share one
client code path:
  groq/openai/gpt-oss-20b        key: GROQ_API_KEY
  openrouter/<org>/<model>       key: OPENROUTER_API_KEY
  gemini/gemini-3.8-flash        key: GEMINI_API_KEY
  scripted                       no key: fixed steps, checks the plumbing only
"""
import json
import os

# Before importing crewAI: no anonymous telemetry or trace upload from test runs.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import crewai  # noqa: E402
from crewai import LLM, Agent, Crew, Task  # noqa: E402
from crewai.llms.base_llm import BaseLLM  # noqa: E402
from crewai.tools import tool  # noqa: E402

from harness import tools as http_tools  # noqa: E402

FRAMEWORK = "crewai"
VERSION = crewai.__version__

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
}

ROLE = "Operations assistant"
GOAL = "Answer questions about customers, orders and services using the company API tools."
BACKSTORY = "You work for an online shop and answer colleagues' questions with data from the company API."


class ScriptedLLM(BaseLLM):
    """Plays back fixed ReAct steps. Exercises tools, proxy and log with no model or key."""

    script: list[str]
    step: int = 0

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None):
        reply = self.script[min(self.step, len(self.script) - 1)]
        self.step += 1
        return reply


def _llm(model: str, temperature: float, task: dict):
    if model == "scripted":
        return ScriptedLLM(model="scripted", script=[
            "Thought: I need data from the company API.\n"
            f"Action: {task['tool']}\n"
            f"Action Input: {json.dumps(task['args'])}",
            "Thought: I now know the final answer\n"
            "Final Answer: scripted run, plumbing check only",
        ])
    provider, _, name = model.partition("/")
    if provider not in PROVIDERS or not name:
        raise ValueError(f"model must be <provider>/<model> with provider in {sorted(PROVIDERS)}")
    base_url, key_env = PROVIDERS[provider]
    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(f"{key_env} is not set; add it to .env")
    return LLM(model=f"openai/{name}", base_url=base_url, api_key=api_key,
               temperature=temperature)


def run(task: dict, model: str, temperature: float, max_iter: int) -> str:
    agent = Agent(
        role=ROLE, goal=GOAL, backstory=BACKSTORY,
        tools=[tool(f.__name__)(f) for f in http_tools.TOOLS],
        llm=_llm(model, temperature, task),
        max_iter=max_iter, allow_delegation=False, verbose=False,
    )
    crew_task = Task(description=task["question"],
                     expected_output="A direct answer to the question.", agent=agent)
    result = Crew(agents=[agent], tasks=[crew_task], verbose=False).kickoff()
    return str(result.raw)
