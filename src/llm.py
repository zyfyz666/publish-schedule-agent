import json
import re
import time
import urllib.request


class Decision:
    def __init__(self, thought, action, args):
        self.thought = thought
        self.action = action
        self.args = args or {}


class MockLLM:
    """离线 Mock 模型：按观察到的工具结果选择下一步动作。

    边界说明：Mock 只用于验证 ReAct 流程骨架与测试确定性，
    不能证明真实模型的决策质量；真实模型路径见 OpenAICompatibleLLM。
    """

    def __init__(self, rules):
        self.rules = rules or {}
        self.name = "mock"

    def decide(self, task, snapshot, tools=None):
        material_id = task.get("material_id")
        if not snapshot["material_fetched"]:
            return Decision(
                "素材元数据尚未读取，先调用 get_material 确认素材存在且信息完整",
                "get_material",
                {"material_id": material_id},
            )
        if snapshot["material_error"]:
            return Decision(
                "素材读取失败，无法继续排期，如实结束并转人工处理",
                "finish",
                {"summary": "素材读取失败：%s" % snapshot["material_error"]},
            )
        material = snapshot["material"]
        missing = [f for f in self.rules.get("required_fields", []) if material.get(f) in (None, "")]
        if missing:
            return Decision(
                "素材缺少必填字段 %s，不能进入排期，请求用户补充" % ", ".join(missing),
                "finish",
                {"summary": "素材信息缺失（%s），需用户补充后重试" % ", ".join(missing)},
            )
        if snapshot["rules_result"] is None:
            return Decision(
                "素材信息完整，调用 check_rules 检查内容规则风险",
                "check_rules",
                {"material_id": material_id},
            )
        if not snapshot["rules_result"].get("passed", False):
            details = "；".join(v["detail"] for v in snapshot["rules_result"].get("violations", []))
            return Decision(
                "规则检查发现风险，阻断自动排期，等待用户处理",
                "finish",
                {"summary": "存在规则风险，已阻断：%s" % details},
            )
        date = task.get("requested_date")
        requested_time = task.get("requested_time")
        req_q = next(
            (q for q in snapshot["slot_queries"] if q["date"] == date and q["time"] == requested_time),
            None,
        )
        if req_q is None:
            return Decision(
                "规则无风险，先查询用户要求的时段 %s %s 是否可用" % (date, requested_time),
                "query_slot",
                {"date": date, "time": requested_time},
            )
        if snapshot["draft"] is not None:
            return self._finish_by_draft(snapshot["draft"])
        if req_q["available"]:
            return Decision(
                "用户要求的时段可用，按原要求保存草稿（不更改硬性发布要求）",
                "save_draft",
                self._save_args(task, date, requested_time),
            )
        occupied_count = sum(1 for q in snapshot["slot_queries"] if q["date"] == date and not q["available"])
        limit = int(self.rules.get("max_search_alternatives", 3))
        if occupied_count > limit:
            return Decision(
                "连续 %s 个备选时段均被占用，停止自动搜索，转人工确定时段" % occupied_count,
                "finish",
                {"summary": "要求的时段及备选时段均被占用，需人工确定时段"},
            )
        alternative = self._next_candidate(requested_time, occupied_count)
        if alternative is None:
            return Decision(
                "已超出当天可发布时段上限，无法自动找到替代时段",
                "finish",
                {"summary": "当天无可自动推荐的空闲时段，需人工确定时段"},
            )
        if not any(q["date"] == date and q["time"] == alternative for q in snapshot["slot_queries"]):
            return Decision(
                "要求的时段 %s 已被占用，先查询 %s 是否可用作为替代（仅查询，不擅自更改用户要求）"
                % (requested_time, alternative),
                "query_slot",
                {"date": date, "time": alternative},
            )
        return Decision(
            "替代时段 %s 可用，保存草稿并标记待用户确认；替代时段与用户硬性要求不一致，必须经用户确认" % alternative,
            "save_draft",
            self._save_args(task, date, alternative),
        )

    def _next_candidate(self, hhmm, occupied_count):
        hour = int(str(hhmm).split(":")[0]) + occupied_count
        latest = int(self.rules.get("latest_publish_hour", 22))
        if hour >= latest:
            return None
        return "%02d:00" % hour

    def _save_args(self, task, date, time):
        requested_time = task.get("requested_time")
        if time == requested_time:
            note = "用户要求时段 %s %s 可用，按原要求保存草稿" % (date, time)
        else:
            note = "原要求时段 %s 已被占用，建议改用 %s，待用户确认" % (requested_time, time)
        return {
            "material_id": task.get("material_id"),
            "date": date,
            "time": time,
            "requested_time": requested_time,
            "note": note,
        }

    def _finish_by_draft(self, draft):
        status = draft.get("status")
        if status == "failed":
            return Decision(
                "保存工具明确返回失败，如实报告失败状态，不虚报保存成功",
                "finish",
                {"summary": "草稿保存失败：%s，需人工处理后重试" % draft.get("message", "存储故障")},
            )
        if status == "duplicate":
            return Decision(
                "重复提交：相同请求的草稿已存在，仅保留一份，不重复创建",
                "finish",
                {"summary": "重复请求已幂等处理：%s" % draft.get("message", "")},
            )
        return Decision(
            "草稿已保存并标记待确认，排期流程结束（未发布）",
            "finish",
            {"summary": "排期草稿已保存，待用户确认后才会进入正式排期"},
        )


class OpenAICompatibleLLM:
    """真实模型客户端（OpenAI 兼容 /chat/completions）。

    通过 JSON 协议驱动 ReAct 循环：每轮模型只输出一个动作，
    由 Agent 执行工具并把观察结果回填，模型据此调整下一步。
    """

    def __init__(self, base_url, api_key, model, max_tokens=2048, temperature=0.0, timeout=120):
        if not base_url or not api_key:
            raise RuntimeError(
                "使用真实模型需设置 OPENAI_BASE_URL 与 OPENAI_API_KEY（复制 .env.example 为 .env 并填写）"
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.name = "openai-compatible:%s" % model

    def decide(self, task, snapshot, tools=None):
        messages = [
            {"role": "system", "content": self._system_prompt(tools or [])},
            {"role": "user", "content": self._user_prompt(task, snapshot)},
        ]
        content = self._chat(messages)
        data = extract_json(content)
        action = str(data.get("action", "")).strip()
        allowed = {t["name"] for t in (tools or [])} | {"finish"}
        if action not in allowed:
            raise RuntimeError("模型返回未知动作 %r，可用动作: %s" % (action, sorted(allowed)))
        return Decision(str(data.get("thought", "")), action, data.get("args") or {})

    def _system_prompt(self, tools):
        lines = []
        for t in tools:
            lines.append("- %s: %s 参数: %s" % (t["name"], t["description"], json.dumps(t["args"], ensure_ascii=False)))
        return (
            "你是内容团队的素材审核与发布排期 Agent。目标：核对素材与审核规则，确认发布时段可用性，"
            "产出无冲突、待用户确认的发布排期草稿。\n"
            "可用工具（每轮只能选择一个）：\n" + "\n".join(lines) + "\n"
            "输出协议：每轮只输出一个 JSON 对象，不要 markdown 代码块，格式：\n"
            '{"thought": "一句话决策依据", "action": "工具名或finish", "args": {工具参数}}\n'
            "finish 时 args 固定为 {\"summary\": \"一句话结论\"}。\n"
            "硬性边界：\n"
            "1. 只保存排期草稿，不存在真实发布能力，任何情况下不得声称已发布；\n"
            "2. 未经用户同意不得更改用户指定的硬性发布要求（日期/时段）；时段被占用时，"
            "先查询相邻整点时段是否空闲，找到后保存替代时段草稿并在 note 中说明待确认原因；\n"
            "3. 保存工具返回 failed 时必须如实报告失败，不得声称保存成功；返回 duplicate 时说明仅保留一份草稿；\n"
            "4. 素材信息缺失或规则风险时，结束流程并说明风险原因与待确认项，不得继续保存；\n"
            "5. 步数有限，完成必要动作后尽快 finish。"
        )

    def _user_prompt(self, task, snapshot):
        return (
            "当前任务: %s\n"
            "当前状态快照（已执行步骤的观察结果）:\n%s\n"
            "请输出下一个动作的 JSON。"
            % (
                json.dumps(task, ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False, indent=2),
            )
        )

    def _chat(self, messages):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        last_error = None
        for attempt in range(4):
            try:
                request = urllib.request.Request(
                    self.base_url + "/chat/completions",
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"].get("content")
            except Exception as exc:
                last_error = exc
                time.sleep([2, 6, 15, 30][attempt])
        raise RuntimeError("模型请求失败: %s" % last_error)


def extract_json(text):
    if not text or not str(text).strip():
        raise RuntimeError("模型未返回内容（推理可能耗尽 max_tokens），可调大 OPENAI_MAX_TOKENS 重试")
    cleaned = str(text).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("模型输出中未找到 JSON: %r" % text[:200])
    return json.loads(cleaned[start : end + 1])
