# 运行 Trace

- 素材：M02
- 用户要求：2026-11-06 18:00 发布
- 模型：mock
- 步数上限：10，实际使用：2
- 运行状态：completed

## 决策循环（模型选择动作 -> 执行工具 -> 观察 -> 调整）

| 步骤 | 动作 | 工具参数 | 观察结果摘要 | 决策依据 |
| --- | --- | --- | --- | --- |
| 1 | get_material | `{"material_id": "M02"}` | 读取成功：M02《周末活动推广》，None 秒，审核状态「审核通过」 | 素材元数据尚未读取，先调用 get_material 确认素材存在且信息完整 |
| 2 | finish | `{"summary": "素材信息缺失（duration_sec），需用户补充后重试"}` | 素材信息缺失（duration_sec），需用户补充后重试 | 素材缺少必填字段 duration_sec，不能进入排期，请求用户补充 |

## 最终结果

```json
{
  "material_id": "M02",
  "requested_slot": {
    "date": "2026-11-06",
    "time": "18:00"
  },
  "requested_slot_available": null,
  "review_status": "missing_info",
  "risk_reasons": [
    "素材信息不完整，缺少必填字段: duration_sec"
  ],
  "suggested_slot": null,
  "slot_differs_from_request": false,
  "needs_user_confirmation": true,
  "pending_confirmations": [
    "素材 M02 缺少必填字段（duration_sec），请补充后重新发起排期"
  ],
  "draft_status": "not_saved",
  "draft_id": null,
  "publish_status": "not_published_draft_only",
  "finish_summary": "素材信息缺失（duration_sec），需用户补充后重试"
}
```
