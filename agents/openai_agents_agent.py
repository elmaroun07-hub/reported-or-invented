"""OpenAI Agents SDK adapter: one agent and the shared HTTP tools."""
import asyncio
import os
from importlib.metadata import version
from pkgutil import extend_path

# Disable trace export before importing the SDK.
os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
os.environ["OTEL_SDK_DISABLED"] = "true"

# The repository and SDK both use "agents". Extend the package search path
# and import SDK submodules without replacing the repository's own package.
import agents as _agents  # noqa: E402

_agents.__path__ = extend_path(_agents.__path__, _agents.__name__)

from agents.agent import Agent  # noqa: E402
from agents.model_settings import ModelSettings  # noqa: E402
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel  # noqa: E402
from agents.run import RunConfig, Runner  # noqa: E402
from agents.tool import function_tool  # noqa: E402
from agents.tracing import set_tracing_disabled  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from harness import tools as http_tools  # noqa: E402
from harness.variants import instructions  # noqa: E402

set_tracing_disabled(True)

FRAMEWORK = "openai_agents"
VERSION = version("openai-agents")

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}

ROLE = "Operations assistant"
GOAL = "Answer questions about customers, orders and services using the company API tools."
BACKSTORY = "You work for an online shop and answer colleagues' questions with data from the company API."


def run(task: dict, model: str, temperature: float, max_iter: int) -> str:
    provider, _, name = model.partition("/")
    if provider == "gemini":
        raise ValueError("gemini is not supported by openai_agents; use groq or openrouter")
    if provider not in PROVIDERS or not name:
        raise ValueError(f"model must be <provider>/<model> with provider in {sorted(PROVIDERS)}")
    if max_iter < 1:
        raise ValueError("max_iter must be at least 1")
    base_url, key_env = PROVIDERS[provider]
    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(f"{key_env} is not set; add it to .env")

    async def execute() -> str:
        async with AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=180.0) as client:
            agent = Agent(
                name=ROLE,
                instructions=instructions(f"{ROLE}\n{GOAL}\n{BACKSTORY}"),
                tools=[function_tool(f, failure_error_function=None) for f in http_tools.tools_for(task)],
                model=OpenAIChatCompletionsModel(model=name, openai_client=client),
                model_settings=ModelSettings(temperature=temperature),
            )
            result = await Runner.run(
                agent, task["question"], max_turns=max_iter,
                run_config=RunConfig(tracing_disabled=True),
            )
            return str(result.final_output)

    return asyncio.run(execute())
