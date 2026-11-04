import json

from .tools import ToolError
from .trace import summarize as summarize_action


class AgentContext:
    def __init__(self):
        self.material = None
        self.material_error = None
        self.material_fetched = False
        self.rules_result = None
        self.slot_queries = []
        self.draft = None

    def apply(self, action, args, obs):
        if action == "get_material":
            self.material_fetched = True
            if obs.get("ok"):
                self.material = obs.get("material")
                self.material_error = None
            else:
                self.material = None
                self.material_error = obs.get("error", "素材读取失败")
        elif action == "check_rules":
            self.rules_result = obs
        elif action == "query_slot":
            self.slot_queries.append(
                {
                    "date": obs.get("date"),
                    "time": obs.get("time"),
                    "available": bool(obs.get("available")),
                    "occupied_by": obs.get("occupied_by"),
                }
            )
        elif action == "save_draft":
            self.draft = obs

    def snapshot(self):
        return {
            "material_fetched": self.material_fetched,
            "material": self.material,
            "material_error": self.material_error,
            "rules_result": self.rules_result,
            "slot_queries": list(self.slot_queries),
            "draft": self.draft,
        }


class ReActAgent:
    """模型选择动作 -> 执行工具 -> 观察结果 -> 模型调整下一步或结束。

    最终结果由工具观察推导，不由模型自由声明，防止虚报保存成功。
    """

    def __init__(self, llm, tools, max_steps=10):
        self.llm = llm
        self.tools = tools
        self.max_steps = max(1, int(max_steps))

    def run(self, task):
        ctx = AgentContext()
        steps = []
        status = "unfinished"
        unfinished_reason = None
        finish_summary = None
        for step_no in range(1, self.max_steps + 1):
            try:
                decision = self.llm.decide(task, ctx.snapshot(), self.tools.list_tools())
            except Exception as exc:
                status = "failed"
                unfinished_reason = "模型决策失败: %s" % exc
                break
            record = {"step": step_no, "action": decision.action, "args": decision.args, "thought": decision.thought}
            if decision.action == "finish":
                finish_summary = str((decision.args or {}).get("summary", ""))
                record["args"] = {"summary": finish_summary}
                record["observation"] = {"summary": finish_summary}
                record["summary"] = finish_summary
                steps.append(record)
                status = "completed"
                break
            try:
                obs = self.tools.execute(decision.action, decision.args)
            except ToolError as exc:
                obs = {"ok": False, "error": str(exc)}
            obs = dict(obs)
            ctx.apply(decision.action, decision.args, obs)
            record["observation"] = obs
            record["summary"] = summarize_action(decision.action, obs)
            steps.append(record)
        if status == "unfinished" and unfinished_reason is None:
            unfinished_reason = "已达到执行步数上限（%d 步），流程未完成" % self.max_steps
        final_result = build_final_result(
            task,
            ctx.snapshot(),
            finish_summary,
            required_fields=self.tools.rules.get("required_fields", []),
        )
        if status != "completed":
            final_result["review_status"] = "incomplete" if final_result["review_status"] in ("unknown",) else final_result["review_status"]
            final_result["pending_confirmations"].append("流程未完成（%s），结果不完整，需人工处理" % unfinished_reason)
            final_result["needs_user_confirmation"] = True
        return {
            "task": task,
            "status": status,
            "unfinished_reason": unfinished_reason,
            "llm": self.llm.name,
            "max_steps": self.max_steps,
            "steps_used": len(steps),
            "final_result": final_result,
            "steps": steps,
        }


def build_final_result(task, snap, finish_summary, required_fields=None):
    material_id = task.get("material_id")
    requested_date = task.get("requested_date")
    requested_time = task.get("requested_time")
    result = {
        "material_id": material_id,
        "requested_slot": {"date": requested_date, "time": requested_time},
        "requested_slot_available": None,
        "review_status": "unknown",
        "risk_reasons": [],
        "suggested_slot": None,
        "slot_differs_from_request": False,
        "needs_user_confirmation": False,
        "pending_confirmations": [],
        "draft_status": "not_saved",
        "draft_id": None,
        "publish_status": "not_published_draft_only",
        "finish_summary": finish_summary,
    }
    if snap["material_error"]:
        result["review_status"] = "not_found"
        result["risk_reasons"].append("素材读取失败：%s" % snap["material_error"])
        result["pending_confirmations"].append("素材不存在或读取失败，请核对素材 ID 后重试")
        result["needs_user_confirmation"] = True
        return result
    material = snap["material"]
    if material is None:
        return result
    missing = [f for f in (required_fields or []) if material.get(f) in (None, "")]
    if missing:
        result["review_status"] = "missing_info"
        result["risk_reasons"].append("素材信息不完整，缺少必填字段: %s" % ", ".join(missing))
        result["pending_confirmations"].append(
            "素材 %s 缺少必填字段（%s），请补充后重新发起排期" % (material_id, ", ".join(missing))
        )
        result["needs_user_confirmation"] = True
        return result
    rules_result = snap["rules_result"]
    if rules_result is not None and not rules_result.get("ok", True):
        result["review_status"] = "rule_risk"
        result["risk_reasons"].append(rules_result.get("error", "规则检查失败"))
        result["needs_user_confirmation"] = True
        return result
    if rules_result is not None and not rules_result.get("passed", False):
        result["review_status"] = "rule_risk"
        result["risk_reasons"] = [v["detail"] for v in rules_result.get("violations", [])]
        result["pending_confirmations"].append(
            "存在规则风险，已阻断自动排期：请修改素材后重审，或由负责人明确确认处理方式"
        )
        result["needs_user_confirmation"] = True
        return result
    result["review_status"] = "no_risk"
    queries = snap["slot_queries"]
    req_q = next((q for q in queries if q["date"] == requested_date and q["time"] == requested_time), None)
    if req_q is not None:
        result["requested_slot_available"] = req_q["available"]
        free_q = req_q if req_q["available"] else None
    else:
        free_q = None
    if free_q is None:
        frees = [q for q in queries if q["date"] == requested_date and q["available"]]
        if frees:
            free_q = frees[-1]
    if free_q is not None:
        result["suggested_slot"] = {"date": free_q["date"], "time": free_q["time"]}
        result["slot_differs_from_request"] = free_q["time"] != requested_time
    if req_q is not None and not req_q["available"]:
        occupied_id = (req_q.get("occupied_by") or {}).get("material_id", "未知素材")
        if free_q is not None:
            result["pending_confirmations"].insert(
                0,
                "用户要求时段 %s %s 已被素材 %s 占用；建议改用 %s %s，此为替代时段，须经用户确认后才生效（当前仅为草稿）"
                % (requested_date, requested_time, occupied_id, free_q["date"], free_q["time"]),
            )
            result["needs_user_confirmation"] = True
        else:
            result["pending_confirmations"].append(
                "用户要求时段 %s %s 已被占用，且未找到可自动推荐的空闲时段，需人工确定时段" % (requested_date, requested_time)
            )
            result["needs_user_confirmation"] = True
    draft = snap["draft"]
    if draft is not None:
        result["draft_status"] = draft.get("status", "not_saved")
        saved = draft.get("draft") or {}
        result["draft_id"] = saved.get("draft_id")
        if draft.get("status") == "failed":
            result["pending_confirmations"].append(
                "草稿保存失败（%s），未生成有效排期，需人工处理后重试" % draft.get("message", "存储故障")
            )
            result["needs_user_confirmation"] = True
        elif draft.get("status") == "duplicate":
            result["pending_confirmations"].append(
                "重复提交已幂等处理：仅保留原有草稿 %s，未重复创建" % result["draft_id"]
            )
    return result
