import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent import ReActAgent
from src.llm import MockLLM
from src.tools import ToolBox
from src.trace import run_to_markdown

DATA = ROOT / "data"
OUT = ROOT / "examples"

CASES = [
    {"dir": "case1_slot_conflict", "material_id": "M01", "requested_date": "2026-11-05", "requested_time": "18:00", "runs": 1},
    {"dir": "case2_missing_info", "material_id": "M02", "requested_date": "2026-11-06", "requested_time": "18:00", "runs": 1},
    {"dir": "case3_rule_risk", "material_id": "M03", "requested_date": "2026-11-06", "requested_time": "18:00", "runs": 1},
    {"dir": "case4_unapproved_material", "material_id": "M04", "requested_date": "2026-11-06", "requested_time": "18:00", "runs": 1},
    {"dir": "case5_duplicate_submit", "material_id": "M01", "requested_date": "2026-11-05", "requested_time": "18:00", "runs": 2},
    {"dir": "case6_save_failure", "material_id": "M_SAVE_FAIL", "requested_date": "2026-11-05", "requested_time": "12:00", "runs": 1},
    {"dir": "case7_step_limit", "material_id": "M01", "requested_date": "2026-11-05", "requested_time": "18:00", "runs": 1, "max_steps": 3},
]


def run_case(case):
    outdir = OUT / case["dir"]
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    spec = {
        "material_id": case["material_id"],
        "requested_date": case["requested_date"],
        "requested_time": case["requested_time"],
    }
    (outdir / "input.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    rules = json.loads((DATA / "rules.json").read_text(encoding="utf-8"))
    drafts = outdir / "drafts.json"
    tools = ToolBox(DATA, drafts_file=drafts)
    agent = ReActAgent(MockLLM(rules), tools, max_steps=case.get("max_steps", 10))
    runs = []
    for i in range(case["runs"]):
        run = agent.run(dict(spec))
        suffix = "" if case["runs"] == 1 else "_run%d" % (i + 1)
        (outdir / ("output%s.json" % suffix)).write_text(
            json.dumps(
                {"status": run["status"], "steps_used": run["steps_used"], "final_result": run["final_result"]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (outdir / ("trace%s.json" % suffix)).write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        (outdir / ("trace%s.md" % suffix)).write_text(run_to_markdown(run), encoding="utf-8")
        runs.append(run)
    if not drafts.exists():
        drafts.write_text('{"drafts": []}', encoding="utf-8")
    return runs


def all_text(run):
    return json.dumps(run, ensure_ascii=False)


def check_case(case, runs):
    checks = []

    def add(name, cond):
        checks.append((name, bool(cond)))

    fr = runs[0]["final_result"]
    steps = runs[0]["steps"]
    if case["dir"] == "case1_slot_conflict":
        ok = (
            runs[0]["status"] == "completed"
            and fr["suggested_slot"] == {"date": "2026-11-05", "time": "19:00"}
            and fr["draft_status"] == "saved"
            and fr["needs_user_confirmation"] is True
            and fr["requested_slot"]["time"] == "18:00"
        )
        add("正常排期：建议 19:00 替代 18:00，草稿待确认", ok)
        add(
            "时段冲突后模型调整：先查 18:00 被占用，再查 19:00",
            any(s["action"] == "query_slot" and s["args"].get("time") == "18:00" for s in steps)
            and any(s["action"] == "query_slot" and s["args"]["time"] == "19:00" for s in steps),
        )
        add("不虚报发布", "已发布" not in all_text(fr) and fr["publish_status"] == "not_published_draft_only")
    elif case["dir"] == "case2_missing_info":
        add(
            "素材信息缺失即阻断",
            fr["review_status"] == "missing_info"
            and any("duration_sec" in r for r in fr["risk_reasons"])
            and not any(s["action"] == "save_draft" for s in steps),
        )
        add("给出待确认项", fr["needs_user_confirmation"] is True and fr["pending_confirmations"])
    elif case["dir"] == "case3_rule_risk":
        add(
            "规则风险阻断（违禁词）",
            fr["review_status"] == "rule_risk"
            and any("违禁词" in r for r in fr["risk_reasons"])
            and fr["draft_status"] == "not_saved",
        )
    elif case["dir"] == "case4_unapproved_material":
        add(
            "未过审素材为风险（状态+时长双违规）",
            fr["review_status"] == "rule_risk" and len([r for r in fr["risk_reasons"]]) >= 2 and fr["draft_status"] == "not_saved",
        )
    elif case["dir"] == "case5_duplicate_submit":
        first, second = runs[0]["final_result"], runs[1]["final_result"]
        stored = json.loads((OUT / case["dir"] / "drafts.json").read_text(encoding="utf-8"))["drafts"]
        add(
            "重复提交只保留一份草稿",
            first["draft_status"] == "saved"
            and second["draft_status"] == "duplicate"
            and first["draft_id"] == second["draft_id"]
            and len(stored) == 1,
        )
    elif case["dir"] == "case6_save_failure":
        failed_obs = [s for s in steps if s["action"] == "save_draft" and s["observation"].get("status") == "failed"]
        add(
            "保存失败如实返回",
            fr["draft_status"] == "failed"
            and any("保存失败" in r for r in fr["pending_confirmations"])
            and len(failed_obs) == 1,
        )
    elif case["dir"] == "case7_step_limit":
        add(
            "步数上限返回明确未完成",
            runs[0]["status"] == "unfinished"
            and "步数上限" in (runs[0].get("unfinished_reason") or "")
            and run_steps_used(runs[0]) == 3
            and fr["draft_status"] == "not_saved",
        )
    return checks


def run_steps_used(run):
    return run["steps_used"]


def main():
    OUT.mkdir(exist_ok=True)
    failures = 0
    total = 0
    for case in CASES:
        runs = run_case(case)
        for name, passed in check_case(case, runs):
            total += 1
            mark = "PASS" if passed else "FAIL"
            print("[%s] %s :: %s" % (mark, case["dir"], name))
            if not passed:
                failures += 1
    print("共 %d 项检查，失败 %d 项" % (total, failures))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
