import json
from datetime import datetime
from pathlib import Path


class ToolError(Exception):
    pass


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


class ToolBox:
    def __init__(self, data_dir, drafts_file=None, simulate_save_failure=False):
        self.data_dir = Path(data_dir)
        self.drafts_file = Path(drafts_file) if drafts_file else self.data_dir / "drafts.json"
        self.rules = load_json(self.data_dir / "rules.json", {})
        self.materials = load_json(self.data_dir / "materials.json", {})
        self.schedule = load_json(self.data_dir / "existing_schedule.json", {})
        self.simulate_save_failure = simulate_save_failure

    def list_tools(self):
        return [
            {
                "name": "get_material",
                "description": "读取素材元数据（标题、时长、审核状态、文案等）；material_id 传空则返回全部素材清单",
                "args": {"material_id": "string，素材 ID，可空"},
            },
            {
                "name": "check_rules",
                "description": "按审核规则检查素材，返回违规项列表与是否通过",
                "args": {"material_id": "string，素材 ID"},
            },
            {
                "name": "query_slot",
                "description": "查询某日期某整点时段的占用情况，返回 available 与占用者信息",
                "args": {"date": "string，YYYY-MM-DD", "time": "string，HH:MM（24 小时制整点）"},
            },
            {
                "name": "save_draft",
                "description": "保存排期草稿（仅草稿，不发布）；同一素材对同一日期与原始要求时段重复提交视为重复请求，幂等返回已有草稿；目标时段已被占用时拒绝保存",
                "args": {
                    "material_id": "string，素材 ID",
                    "date": "string，YYYY-MM-DD",
                    "time": "string，HH:MM，实际保存的时段",
                    "requested_time": "string 或 null，用户原始要求的时段",
                    "note": "string，保存说明（如替代时段待确认原因）",
                },
            },
        ]

    def execute(self, action, args):
        if action == "get_material":
            return self.get_material(args.get("material_id"))
        if action == "check_rules":
            return self.check_rules(args.get("material_id"))
        if action == "query_slot":
            return self.query_slot(args.get("date"), args.get("time"))
        if action == "save_draft":
            return self.save_draft(args)
        raise ToolError("未知工具: %s，可用工具: %s" % (action, ", ".join(t["name"] for t in self.list_tools())))

    def get_material(self, material_id):
        if not material_id:
            materials = [self.materials[k] for k in sorted(self.materials)]
            return {"ok": True, "materials": materials}
        material = self.materials.get(material_id)
        if material is None:
            return {"ok": False, "error": "素材 %s 不存在" % material_id, "material": None}
        return {"ok": True, "material": material}

    def check_rules(self, material_id):
        material = self.materials.get(material_id)
        if material is None:
            return {
                "ok": False,
                "error": "素材 %s 不存在，无法检查规则" % material_id,
                "material_id": material_id,
                "passed": False,
                "violations": [],
            }
        violations = []
        for field in self.rules.get("required_fields", []):
            if material.get(field) in (None, ""):
                violations.append({"rule": "required_fields", "detail": "缺少必填字段 %s" % field})
        status = material.get("review_status")
        allowed = self.rules.get("allowed_review_status", [])
        if status not in allowed:
            violations.append(
                {
                    "rule": "allowed_review_status",
                    "detail": "素材审核状态为「%s」，不在允许范围「%s」内" % (status, "、".join(allowed)),
                }
            )
        duration = material.get("duration_sec")
        max_duration = self.rules.get("max_duration_sec")
        if isinstance(duration, int) and max_duration is not None and duration > max_duration:
            violations.append(
                {"rule": "max_duration_sec", "detail": "素材时长 %s 秒，超过上限 %s 秒" % (duration, max_duration)}
            )
        text = json.dumps(material, ensure_ascii=False)
        for word in self.rules.get("forbidden_words", []):
            if word in text:
                violations.append({"rule": "forbidden_words", "detail": "素材文案包含违禁词「%s」" % word})
        return {
            "ok": True,
            "material_id": material_id,
            "passed": not violations,
            "violations": violations,
        }

    def query_slot(self, date, time):
        if not date or not time:
            return {"ok": False, "error": "query_slot 需要 date 与 time 参数", "available": False, "occupied_by": None}
        day = self.schedule.get(date, {})
        if time in day:
            return {
                "ok": True,
                "date": date,
                "time": time,
                "available": False,
                "occupied_by": day[time],
            }
        note = None if date in self.schedule else "该日期暂无已排期记录，视为空闲"
        return {"ok": True, "date": date, "time": time, "available": True, "occupied_by": None, "note": note}

    def save_draft(self, args):
        material_id = args.get("material_id")
        date = args.get("date")
        time = args.get("time")
        if not material_id or not date or not time:
            return {
                "ok": False,
                "status": "failed",
                "draft": None,
                "message": "保存草稿需要 material_id、date、time 参数",
            }
        if material_id not in self.materials:
            return {
                "ok": True,
                "status": "failed",
                "draft": None,
                "message": "素材 %s 不存在，拒绝保存" % material_id,
            }
        day = self.schedule.get(date, {})
        if time in day:
            occupied = day[time]
            return {
                "ok": True,
                "status": "failed",
                "draft": None,
                "message": "目标时段 %s %s 已被素材 %s 占用，拒绝保存；请改用空闲时段" % (date, time, occupied.get("material_id", "未知")),
            }
        drafts = load_json(self.drafts_file, {"drafts": []})
        requested_time = args.get("requested_time") or time
        for existing in drafts["drafts"]:
            if (
                existing["material_id"] == material_id
                and existing["date"] == date
                and str(existing.get("requested_time") or existing["time"]) == str(requested_time)
            ):
                return {
                    "ok": True,
                    "status": "duplicate",
                    "draft": existing,
                    "message": "素材 %s 对 %s %s 的排期请求已有待确认草稿 %s（保存时段 %s），未重复创建" % (
                        material_id,
                        date,
                        requested_time,
                        existing["draft_id"],
                        existing["time"],
                    ),
                }
        if self.simulate_save_failure or self.materials.get(material_id, {}).get("inject_save_failure"):
            return {
                "ok": True,
                "status": "failed",
                "draft": None,
                "message": "草稿保存失败：存储写入故障（模拟故障注入）",
            }
        record = {
            "draft_id": "D-%s-%s-%s" % (material_id, date, str(time).replace(":", "")),
            "material_id": material_id,
            "date": date,
            "time": time,
            "requested_time": requested_time,
            "status": "pending_confirmation",
            "note": args.get("note") or "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        drafts["drafts"].append(record)
        self.drafts_file.parent.mkdir(parents=True, exist_ok=True)
        with self.drafts_file.open("w", encoding="utf-8") as f:
            json.dump(drafts, f, ensure_ascii=False, indent=2)
        return {
            "ok": True,
            "status": "saved",
            "draft": record,
            "message": "草稿已保存（仅草稿，未发布，需用户确认）",
        }
