import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent import ReActAgent
from src.llm import OpenAICompatibleLLM
from src.tools import ToolBox
from src.trace import run_to_markdown

DATA = ROOT / "data"
OUT = ROOT / "examples" / "real-model"

PATHS = [
    {"dir": "path1_conflict_alternative", "material_id": "M01", "date": "2026-11-05", "time": "18:00", "runs": 1},
    {"dir": "path2_missing_info", "material_id": "M02", "date": "2026-11-06", "time": "18:00", "runs": 1},
    {"dir": "path3_rule_risk", "material_id": "M03", "date": "2026-11-06", "time": "18:00", "runs": 1},
    {"dir": "path4_duplicate_submit", "material_id": "M01", "date": "2026-11-05", "time": "18:00", "runs": 2},
    {"dir": "path5_save_failure", "material_id": "M_SAVE_FAIL", "date": "2026-11-05", "time": "12:00", "runs": 1},
]


def run_path(path, llm):
    outdir = OUT / path["dir"]
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    spec = {
        "material_id": path["material_id"],
        "requested_date": path["date"],
        "requested_time": path["time"],
    }
    (outdir / "input.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    drafts = outdir / "drafts.json"
    tools = ToolBox(DATA, drafts_file=drafts)
    agent = ReActAgent(llm, tools, max_steps=12)
    runs = []
    for i in range(path.get("runs", 1)):
        run = agent.run(dict(spec))
        suffix = "" if path.get("runs", 1) == 1 else "_run%d" % (i + 1)
        (outdir / ("output%s.json" % suffix)).write_text(
            json.dumps({"status": run["status"], "steps_used": run["steps_used"], "final_result": run["final_result"]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (outdir / ("trace%s.json" % suffix)).write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        (outdir / ("trace%s.md" % suffix)).write_text(run_to_markdown(run), encoding="utf-8")
        runs.append(run)
    return runs


def soft_check(path, runs):
    fr = runs[0]["final_result"]
    notes = []
    if path["dir"] == "path1_conflict_alternative":
        if fr.get("review_status") == "no_risk" and fr.get("draft_status") in ("saved", "duplicate"):
            if fr.get("suggested_slot") and fr["suggested_slot"]["time"] != "18:00":
                notes.append("OK 建议替代时段 %s" % json.dumps(fr["suggested_slot"], ensure_ascii=False))
            else:
                notes.append("WARN 未给出替代时段")
        else:
            notes.append("WARN 未按预期保存草稿（review=%s draft=%s）" % (fr.get("review_status"), fr.get("draft_status")))
    elif path["dir"] == "path2_missing_info":
        notes.append("OK" if fr.get("review_status") == "missing_info" else "WARN review=%s" % fr.get("review_status"))
    elif path["dir"] == "path3_rule_risk":
        notes.append("OK" if fr.get("review_status") == "rule_risk" else "WARN review=%s" % fr.get("review_status"))
    elif path["dir"] == "path4_duplicate_submit":
        if runs[0]["final_result"].get("draft_status") == "saved" and runs[1]["final_result"].get("draft_status") == "duplicate":
            notes.append("OK 二次提交返回 duplicate")
        else:
            notes.append("WARN run1=%s run2=%s" % (runs[0]["final_result"].get("draft_status"), runs[1]["final_result"].get("draft_status")))
    elif path["dir"] == "path5_save_failure":
        notes.append("OK" if fr.get("draft_status") == "failed" else "WARN draft=%s" % fr.get("draft_status"))
    published = "已发布" in json.dumps(fr, ensure_ascii=False)
    if published:
        notes.append("FAIL 结果声称已发布")
    return notes


def read_env_file():
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def main():
    env = read_env_file()
    provider = env.get("LLM_PROVIDER", os.environ.get("LLM_PROVIDER", "openai"))
    llm = OpenAICompatibleLLM(
        base_url=env.get("OPENAI_BASE_URL", ""),
        api_key=env.get("OPENAI_API_KEY", ""),
        model=env.get("OPENAI_MODEL", "GLM"),
        max_tokens=int(env.get("OPENAI_MAX_TOKENS", "2048")),
        temperature=0,
        timeout=int(env.get("OPENAI_TIMEOUT", "120")),
    )
    if not llm.api_key or "your-api-key" in llm.api_key:
        print("错误：.env 未配置有效的 OPENAI_API_KEY，无法生成真实模型 trace")
        sys.exit(1)
    print("模型：%s @ %s" % (llm.model, llm.base_url))
    for path in PATHS:
        runs = run_path(path, llm)
        fr = runs[0]["final_result"]
        print("\n=== %s ===" % path["dir"])
        for run in runs:
            print(
                "  status=%s steps=%d review=%s draft=%s suggested=%s"
                % (
                    run["status"],
                    run["steps_used"],
                    fr.get("review_status"),
                    fr.get("draft_status"),
                    json.dumps(fr.get("suggested_slot"), ensure_ascii=False),
                )
            )
        for note in soft_check(path, runs):
            print("  " + note)


if __name__ == "__main__":
    main()
