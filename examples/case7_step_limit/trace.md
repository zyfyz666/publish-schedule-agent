# 运行 Trace

- 素材：M01
- 用户要求：2026-11-05 18:00 发布
- 模型：mock
- 步数上限：3，实际使用：3
- 运行状态：unfinished（已达到执行步数上限（3 步），流程未完成）

## 决策循环（模型选择动作 -> 执行工具 -> 观察 -> 调整）

| 步骤 | 动作 | 工具参数 | 观察结果摘要 | 决策依据 |
| --- | --- | --- | --- | --- |
| 1 | get_material | `{"material_id": "M01"}` | 读取成功：M01《秋季新品预告》，30 秒，审核状态「审核通过」 | 素材元数据尚未读取，先调用 get_material 确认素材存在且信息完整 |
| 2 | check_rules | `{"material_id": "M01"}` | 规则检查通过，无违规 | 素材信息完整，调用 check_rules 检查内容规则风险 |
| 3 | query_slot | `{"date": "2026-11-05", "time": "18:00"}` | 时段 2026-11-05 18:00：已被占用（占用者：M09 双11预售直播回放） | 规则无风险，先查询用户要求的时段 2026-11-05 18:00 是否可用 |

## 最终结果

```json
{
  "material_id": "M01",
  "requested_slot": {
    "date": "2026-11-05",
    "time": "18:00"
  },
  "requested_slot_available": false,
  "review_status": "no_risk",
  "risk_reasons": [],
  "suggested_slot": null,
  "slot_differs_from_request": false,
  "needs_user_confirmation": true,
  "pending_confirmations": [
    "用户要求时段 2026-11-05 18:00 已被占用，且未找到可自动推荐的空闲时段，需人工确定时段",
    "流程未完成（已达到执行步数上限（3 步），流程未完成），结果不完整，需人工处理"
  ],
  "draft_status": "not_saved",
  "draft_id": null,
  "publish_status": "not_published_draft_only",
  "finish_summary": null
}
```
