import json

from src.agent import build_final_result  # noqa: F401
from src.tools import ToolBox


def test_normal_scheduling_with_slot_conflict_suggests_alternative(agent_factory, make_task, tmp_path):
    drafts = tmp_path / "drafts.json"
    agent = agent_factory(drafts_file=drafts)
    run = agent.run(make_task("M01"))
    assert run["status"] == "completed"
    fr = run["final_result"]
    assert fr["review_status"] == "no_risk"
    assert fr["requested_slot"] == {"date": "2026-11-05", "time": "18:00"}
    assert fr["requested_slot_available"] is False
    assert fr["suggested_slot"] == {"date": "2026-11-05", "time": "19:00"}
    assert fr["slot_differs_from_request"] is True
    assert fr["needs_user_confirmation"] is True
    assert fr["draft_status"] == "saved"
    assert fr["draft_id"] == "D-M01-2026-11-05-1900"
    assert fr["publish_status"] == "not_published_draft_only"
    assert any("待确认" in msg or "确认" in msg for msg in fr["pending_confirmations"])
    query_times = [s["args"]["time"] for s in run["steps"] if s["action"] == "query_slot"]
    assert query_times == ["18:00", "19:00"]
    stored = json.loads(drafts.read_text(encoding="utf-8"))["drafts"]
    assert len(stored) == 1
    assert stored[0]["status"] == "pending_confirmation"


def test_trace_shows_model_adjust_after_occupied_result(agent_factory, make_task):
    run = agent_factory().run(make_task("M01"))
    steps = run["steps"]
    occupied_step = next(s for s in steps if s["action"] == "query_slot" and s["args"]["time"] == "18:00")
    assert occupied_step["observation"]["available"] is False
    next_action = steps[steps.index(occupied_step) + 1]
    assert next_action["action"] == "query_slot"
    assert next_action["args"]["time"] == "19:00"
    assert "占用" in next_step_thought(steps, steps.index(occupied_step))


def next_step_thought(run_steps, index):
    return run_steps[run_steps.index(run_steps[index]) + 1]["thought"]


def test_missing_material_info_blocks_and_requests_user(agent_factory, make_task):
    agent = agent_factory()
    run = agent.run(make_task("M02", date="2026-11-06"))
    assert run["status"] == "completed"
    fr = run["final_result"]
    assert fr["review_status"] == "missing_info" or any("duration_sec" in r for r in fr["risk_reasons"])
    assert fr["draft_status"] == "not_saved"
    actions = [s["action"] for s in run["steps"]]
    assert "save_draft" not in actions
    assert any("补充" in msg for msg in fr["pending_confirmations"])


def test_rule_risk_blocks_scheduling(agent_factory, make_task):
    run = agent_factory().run(make_task("M03", date="2026-11-06", time="18:00"))
    assert run["status"] == "completed"
    fr = run["final_result"]
    assert fr["review_status"] == "rule_risk"
    assert any("违禁词" in r for r in fr["risk_reasons"])
    assert fr["draft_status"] == "not_saved"


def test_unapproved_material_is_risk(agent_factory, make_task):
    run = agent_factory().run(make_task("M04", date="2026-11-06", time="18:00"))
    fr = run["final_result"]
    assert fr["review_status"] == "rule_risk"
    assert any("待审核" in r or "审核状态" in r for r in fr["risk_reasons"])
    assert fr["draft_status"] == "not_saved"


def test_duplicate_submission_creates_only_one_draft(agent_factory, make_task, tmp_path):
    drafts = tmp_path / "drafts.json"
    agent = agent_factory(drafts_file=drafts)
    run1 = agent.run(make_task("M01"))
    run2 = agent.run(make_task("M01"))
    assert run1["final_result"]["draft_status"] == "saved"
    assert run2["final_result"]["draft_status"] == "duplicate"
    assert run1["final_result"]["draft_id"] == run2["final_result"]["draft_id"]
    stored = json.loads(drafts.read_text(encoding="utf-8"))["drafts"]
    assert len(stored) == 1
    assert stored[0]["time"] == "19:00"
    assert stored[0]["requested_time"] == "18:00"


def test_save_failure_is_explicit_not_faked(agent_factory, make_task, tmp_path):
    drafts = tmp_path / "drafts.json"
    run = agent_factory(drafts_file=drafts).run(make_task("M_SAVE_FAIL", time="12:00"))
    assert run["status"] == "completed"
    fr = run["final_result"]
    assert fr["draft_status"] == "failed"
    text = json.dumps(fr, ensure_ascii=False)
    assert "保存失败" in text
    saved_obs = [s for s in run["steps"] if s["action"] == "save_draft"]
    assert len(saved_obs) == 1
    assert saved_obs[0]["observation"]["status"] == "failed"
    assert not drafts.exists()


def test_step_limit_returns_explicit_unfinished(agent_factory, make_task):
    run = agent_factory(max_steps=3).run(make_task("M01"))
    assert run["status"] == "unfinished"
    assert run["steps_used"] == 3
    assert "步数上限" in run["unfinished_reason"]
    fr = run["final_result"]
    assert fr["draft_status"] == "not_saved"
    assert fr["publish_status"] == "not_published_draft_only"
    assert any("未完成" in msg for msg in fr["pending_confirmations"])


def test_never_claims_published(agent_factory, make_task, tmp_path):
    results = [
        agent_factory(drafts_file=tmp_path / "a.json").run(make_task("M01")),
        agent_factory(drafts_file=tmp_path / "b.json").run(make_task("M02", date="2026-11-06")),
        agent_factory(drafts_file=tmp_path / "b.json").run(make_task("M03", date="2026-11-06", time="18:00")),
        agent_factory(drafts_file=tmp_path / "c.json").run(make_task("M_SAVE_FAIL", time="12:00")),
    ]
    for run in results:
        text = json.dumps(run["final_result"], ensure_ascii=False)
        assert "已发布" not in text
        assert run["final_result"]["publish_status"] == "not_published_draft_only"


def test_hard_requirement_not_silently_changed(agent_factory, make_task):
    run = agent_factory().run(make_task("M01"))
    fr = run["final_result"]
    assert fr["requested_slot"]["time"] == "18:00"
    assert fr["suggested_slot"]["time"] == "19:00"
    assert fr["slot_differs_from_request"] is True
    assert fr["needs_user_confirmation"] is True
    draft_saved = [s for s in run["steps"] if s["action"] == "save_draft"]
    assert draft_saved and draft_saved[0]["args"]["requested_time"] == "18:00"


def test_build_final_result_without_any_tool_observation(make_task):
    snap = {
        "material_fetched": False,
        "material": None,
        "material_error": None,
        "rules_result": None,
        "slot_queries": [],
        "draft": None,
    }
    fr = build_final_result(make_task("M01"), snap, None)
    assert fr["review_status"] == "unknown"
    assert fr["draft_status"] == "not_saved"
