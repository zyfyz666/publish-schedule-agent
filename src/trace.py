import json


def summarize(action, obs):
    if not obs.get("ok", True):
        return "工具返回失败：%s" % obs.get("error", "未知错误")
    if action == "get_material":
        if obs.get("materials") is not None:
            return "返回素材列表，共 %d 项" % len(obs["materials"])
        m = obs.get("material") or {}
        return "读取成功：%s《%s》，%s 秒，审核状态「%s」" % (
            m.get("id"),
            m.get("title"),
            m.get("duration_sec"),
            m.get("review_status"),
        )
    if action == "check_rules":
        violations = obs.get("violations") or []
        if violations:
            return "发现 %d 项违规：%s" % (len(violations), "；".join(v["detail"] for v in violations))
        return "规则检查通过，无违规"
    if action == "query_slot":
        line = "时段 %s %s：%s" % (obs.get("date"), obs.get("time"), "可用" if obs.get("available") else "已被占用")
        occupied = obs.get("occupied_by")
        if occupied:
            line += "（占用者：%s %s）" % (occupied.get("material_id", ""), occupied.get("title", ""))
        if obs.get("note"):
            line += "，%s" % obs["note"]
        return line
    if action == "save_draft":
        line = "保存结果：%s" % obs.get("status")
        saved = obs.get("draft") or {}
        if saved.get("draft_id"):
            line += "，draft_id=%s" % saved["draft_id"]
        if obs.get("message"):
            line += "，%s" % obs["message"]
        return line
    return json.dumps(obs, ensure_ascii=False)[:200]


def _cell(text):
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def run_to_markdown(run):
    task = run["task"]
    lines = []
    lines.append("# 运行 Trace")
    lines.append("")
    lines.append("- 素材：%s" % task.get("material_id"))
    lines.append("- 用户要求：%s %s 发布" % (task.get("requested_date"), task.get("requested_time")))
    lines.append("- 模型：%s" % run["llm"])
    lines.append("- 步数上限：%d，实际使用：%d" % (run["max_steps"], run["steps_used"]))
    lines.append("- 运行状态：%s%s" % (run["status"], ("（%s）" % run["unfinished_reason"]) if run.get("unfinished_reason") else ""))
    lines.append("")
    lines.append("## 决策循环（模型选择动作 -> 执行工具 -> 观察 -> 调整）")
    lines.append("")
    lines.append("| 步骤 | 动作 | 工具参数 | 观察结果摘要 | 决策依据 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for s in run["steps"]:
        args = json.dumps(s.get("args") or {}, ensure_ascii=False)
        lines.append("| %s | %s | `%s` | %s | %s |" % (s["step"], s["action"], _cell(args), _cell(s.get("summary")), _cell(s.get("thought"))))
    lines.append("")
    lines.append("## 最终结果")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(run["final_result"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)
