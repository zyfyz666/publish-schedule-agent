import json

from src.tools import ToolBox


def test_get_material_existing(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.execute("get_material", {"material_id": "M01"})
    assert obs["ok"] is True
    assert obs["material"]["title"] == "秋季新品预告"
    assert obs["material"]["duration_sec"] == 30


def test_get_material_unknown(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.execute("get_material", {"material_id": "M99"})
    assert obs["ok"] is False
    assert obs["material"] is None
    assert "不存在" in obs["error"]


def test_get_material_list(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.execute("get_material", {})
    assert obs["ok"] is True
    assert len(obs["materials"]) == 5


def test_check_rules_pass(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.execute("check_rules", {"material_id": "M01"})
    assert obs["ok"] is True
    assert obs["passed"] is True
    assert obs["violations"] == []


def test_check_rules_forbidden_words(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.execute("check_rules", {"material_id": "M03"})
    assert obs["passed"] is False
    details = "；".join(v["detail"] for v in obs["violations"])
    assert "违禁词" in details
    assert "全网最低价" in details or "绝对正品" in details


def test_check_rules_unapproved_and_duration(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.execute("check_rules", {"material_id": "M04"})
    assert obs["passed"] is False
    rules_hit = {v["rule"] for v in obs["violations"]}
    assert "allowed_review_status" in rules_hit
    assert "max_duration_sec" in rules_hit


def test_check_rules_missing_field(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.execute("check_rules", {"material_id": "M02"})
    assert obs["passed"] is False
    assert any(v["rule"] == "required_fields" and "duration_sec" in v["detail"] for v in obs["violations"])


def test_query_slot_occupied_and_free(data_dir):
    tools = ToolBox(data_dir)
    occupied = tools.execute("query_slot", {"date": "2026-11-05", "time": "18:00"})
    assert occupied["available"] is False
    assert occupied["occupied_by"]["material_id"] == "M09"
    free = tools.execute("query_slot", {"date": "2026-11-05", "time": "19:00"})
    assert free["available"] is True


def test_query_slot_unknown_date_treated_free(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.execute("query_slot", {"date": "2026-12-01", "time": "10:00"})
    assert obs["available"] is True
    assert "视为空闲" in (obs.get("note") or "")


def test_save_draft_then_duplicate_keeps_single_record(data_dir, tmp_path):
    drafts = tmp_path / "drafts.json"
    tools = ToolBox(data_dir, drafts_file=drafts)
    first = tools.save_draft({"material_id": "M01", "date": "2026-11-05", "time": "19:00", "requested_time": "18:00", "note": "替代时段"})
    assert first["status"] == "saved"
    second = tools.save_draft({"material_id": "M01", "date": "2026-11-05", "time": "19:00", "requested_time": "18:00"})
    assert second["status"] == "duplicate"
    assert second["draft"]["draft_id"] == first["draft"]["draft_id"]
    stored = json.loads(drafts.read_text(encoding="utf-8"))["drafts"]
    assert len(stored) == 1
    assert stored[0]["status"] == "pending_confirmation"


def test_save_draft_refuses_occupied_slot(data_dir):
    tools = ToolBox(data_dir)
    obs = tools.save_draft({"material_id": "M01", "date": "2026-11-05", "time": "18:00"})
    assert obs["status"] == "failed"
    assert "占用" in obs["message"]


def test_save_draft_failure_injection(data_dir, tmp_path):
    drafts = tmp_path / "drafts.json"
    tools = ToolBox(data_dir, drafts_file=drafts)
    obs = tools.save_draft({"material_id": "M_SAVE_FAIL", "date": "2026-11-05", "time": "12:00", "requested_time": "12:00"})
    assert obs["ok"] is True
    assert obs["status"] == "failed"
    assert obs["draft"] is None
    assert "保存失败" in obs["message"]


def test_save_draft_simulated_global_failure(data_dir, tmp_path):
    tools = ToolBox(data_dir, drafts_file=tmp_path / "d.json", simulate_save_failure=True)
    obs = tools.save_draft({"material_id": "M01", "date": "2026-11-05", "time": "19:00"})
    assert obs["status"] == "failed"


def test_unknown_tool_raises(data_dir):
    tools = ToolBox(data_dir)
    try:
        tools.execute("publish_now", {})
        assert False, "应抛出 ToolError"
    except Exception as exc:
        assert "未知工具" in str(exc)
