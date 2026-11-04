import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent import ReActAgent
from src.llm import MockLLM
from src.tools import ToolBox


@pytest.fixture
def data_dir(tmp_path):
    for name in ("materials.json", "rules.json", "existing_schedule.json"):
        (tmp_path / name).write_bytes((ROOT / "data" / name).read_bytes())
    return tmp_path


@pytest.fixture
def agent_factory(data_dir):
    def _factory(drafts_file=None, max_steps=10):
        rules = json.loads((data_dir / "rules.json").read_text(encoding="utf-8"))
        tools = ToolBox(data_dir, drafts_file=drafts_file)
        return ReActAgent(MockLLM(rules), tools, max_steps=max_steps)

    return _factory


@pytest.fixture
def make_task():
    def _make(material_id, date="2026-11-05", time="18:00"):
        return {"material_id": material_id, "requested_date": date, "requested_time": time}

    return _make
