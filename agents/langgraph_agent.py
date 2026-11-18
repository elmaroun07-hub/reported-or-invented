"""LangGraph adapter: one ReAct agent (langchain.agents.create_agent, which runs on a
LangGraph state graph), one question, the shared HTTP tools.

The baseline instructions are neutral on purpose: nothing tells it how to treat
a failed or empty tool result, so a run measures the framework + model default,
not a prompt fix. The system prompt carries crewAI's role, backstory and goal word
for word, in the same order and wording crewAI uses for an agent's identity.

Models are given as <provider>/<model>. Groq and OpenRouter go through the
OpenAI-compatible chat client (langchain-openai) with an explicit base URL:
  groq/openai/gpt-oss-20b        key: GROQ_API_KEY
  openrouter/<org>/<model>       key: OPENROUTER_API_KEY
Gemini is not wired into this adapter (ValueError).

Tool errors: the default ToolNode handler turns only argument-validation errors into
a message for the model and re-raises everything else, so a connection error from the
tools propagates out of run() as an infrastructure fault, as in the other adapters.
"""
import os

# Before importing langchain: no LangSmith tracing, whatever the environment says.
for _var in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
    os.environ[_var] = "false"

from importlib.metadata import version  # noqa: E402

from langchain.agents import create_agent  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from harness import tools as http_tools  # noqa: E402
from harness.variants import instructions  # noqa: E402

FRAMEWORK = "langgraph"
VERSION = version("langgraph")

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}

ROLE = "Operations assistant"
GOAL = "Answer questions about customers, orders and services using the company API tools."
BACKSTORY = "You work for an online shop and answer colleagues' questions with data from the company API."


def _llm(model: str, temperature: float) -> ChatOpenAI:
    provider, _, name = model.partition("/")
    if provider == "gemini":
        raise ValueError("the langgraph adapter does not support gemini; use groq/<model> or openrouter/<model>")
    if provider not in PROVIDERS or not name:
        raise ValueError(f"model must be <provider>/<model> with provider in {sorted(PROVIDERS)}")
    base_url, key_env = PROVIDERS[provider]
    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(f"{key_env} is not set; add it to .env")
    return ChatOpenAI(model=name, base_url=base_url, api_key=api_key, temperature=temperature)


def run(task: dict, model: str, temperature: float, max_iter: int) -> str:
    agent = create_agent(
        _llm(model, temperature),
        tools=[tool(f) for f in http_tools.tools_for(task)],
        system_prompt=instructions(f"You are {ROLE}. {BACKSTORY}\nYour personal goal is: {GOAL}"),
    )
    # Every model call and every tool step is one graph step: max_iter model calls
    # with a tool step between each need 2 * max_iter - 1 steps. A model that is
    # still calling tools after that raises GraphRecursionError (propagates).
    result = agent.invoke(
        {"messages": [{"role": "user", "content": task["question"]}]},
        config={"recursion_limit": 2 * max_iter},
    )
    return result["messages"][-1].text
