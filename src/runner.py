import json
import os
from pathlib import Path

from .agent import ReActAgent
from .llm import MockLLM, OpenAICompatibleLLM
from .tools import ToolBox

ROOT = Path(__file__).resolve().parents[1]


def load_env(env_file=None):
    path = Path(env_file) if env_file else ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_agent(data_dir, drafts_file=None, provider=None, max_steps=10, simulate_save_failure=False):
    data_dir = Path(data_dir)
    provider = provider or os.environ.get("LLM_PROVIDER", "mock")
    rules = {}
    rules_file = data_dir / "rules.json"
    if rules_file.exists():
        rules = json.loads(rules_file.read_text(encoding="utf-8"))
    tools = ToolBox(data_dir, drafts_file=drafts_file, simulate_save_failure=simulate_save_failure)
    if provider in ("mock", None, ""):
        llm = MockLLM(rules)
    elif provider in ("openai", "openai-compatible", "csu"):
        llm = OpenAICompatibleLLM(
            base_url=os.environ.get("OPENAI_BASE_URL", ""),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("OPENAI_MODEL", "GLM"),
            max_tokens=int(os.environ.get("OPENAI_MAX_TOKENS", "2048")),
            temperature=float(os.environ.get("OPENAI_TEMPERATURE", "0")),
            timeout=int(os.environ.get("OPENAI_TIMEOUT", "120")),
        )
    else:
        raise RuntimeError("未知 LLM_PROVIDER: %s（可选 mock / openai）" % provider)
    return ReActAgent(llm, tools, max_steps=max_steps)


def run_task(task, data_dir, drafts_file=None, provider=None, max_steps=10, simulate_save_failure=False):
    agent = build_agent(data_dir, drafts_file=drafts_file, provider=provider, max_steps=max_steps, simulate_save_failure=simulate_save_failure)
    return agent.run(task)
