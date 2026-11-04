# 示例：输入 / 输出 / 运行记录

每个目录包含：`input.json`（任务输入）、`output.json`（最终结果）、`trace.md`（决策运行记录，人读）、`trace.json`（完整运行记录，含每步观察原文）、`drafts.json`（草稿存储终态）。

全部由 `scripts/gen_examples.py`（离线 Mock 模型）生成，可复现：

```bash
py -3 -X utf8 scripts/gen_examples.py
```

## 案例与验收点映射

| 目录 | 素材 | 场景 | 验收点 | 预期结果 |
| --- | --- | --- | --- | --- |
| case1_slot_conflict | M01 | 要求 11-05 18:00，已被 M09 占用 | 正常排期 + 时段冲突 | 查 19:00 空闲 → 保存替代时段草稿，needs_user_confirmation=true |
| case2_missing_info | M02 | 素材缺 duration_sec | 素材信息缺失 | review=missing_info，不保存，转人工补充 |
| case3_rule_risk | M03 | 文案含违禁词 | 规则风险 | review=rule_risk，不保存 |
| case4_unapproved_material | M04 | 待审核 + 120s 超上限 | 规则风险（双违规） | review=rule_risk，不保存 |
| case5_duplicate_submit | M01 | 同一请求连续提交两次 | 重复提交去重 | run1=saved，run2=duplicate，草稿仅 1 条 |
| case6_save_failure | M_SAVE_FAIL | 存储故障注入 | 保存失败如实返回 | draft_status=failed，草稿文件为空 |
| case7_step_limit | M01 | max_steps=3 | 步数上限 | status=unfinished + 未完成原因，未保存草稿 |

## 真实模型运行记录（examples/real-model/）

由 `scripts/gen_real_traces.py` 使用 GLM（OpenAI 兼容接口）生成，验证同一 Agent 流程在真实模型下的行为：

| 路径 | 场景 | 结果 |
| --- | --- | --- |
| path1_conflict_alternative | 18:00 被占用 | 查 19:00 空闲 → 保存替代草稿（6 步） |
| path2_missing_info | 缺 duration_sec | 检查后立即终止（3 步） |
| path3_rule_risk | 违禁词 | 立即终止（3 步） |
| path4_duplicate_submit | 重复提交 | run2 返回 duplicate，仅 1 份草稿 |
| path5_save_failure | 保存故障 | 如实返回 failed，无草稿产生 |

> 真实模型与 Mock 的步数可能略有差异（探索路径不同），但最终结果与边界行为一致：不发布、不改硬性要求、失败如实报告。
