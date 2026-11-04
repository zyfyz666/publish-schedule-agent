# 03 评测方案与结果

## 评测矩阵：验收点 → 示例 → 结果

每个示例目录（`examples/<case>/`）包含：`input.json`（输入）、`output.json`（最终结果）、`trace.md`（决策过程）、`trace.json`（完整运行记录）、`drafts.json`（草稿存储状态）。

| # | 验收点 | 示例 | 输入 | 关键断言 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 1 | 正常排期 | case1_slot_conflict | M01 @ 11-05 18:00（被 M09 占用） | query 18:00→占用→query 19:00→空闲→保存草稿 19:00，needs_user_confirmation=true | PASS |
| 2 | 素材信息缺失 | case2_missing_info | M02（缺 duration_sec）@ 11-06 | review_status=missing_info，未调用 save_draft，转人工补充 | PASS |
| 3 | 规则风险 | case3_rule_risk | M03（含违禁词）@ 11-06 | review_status=rule_risk，draft_status=not_saved | PASS |
| 4 | 时段冲突与替代建议 | case1（同上） | 同上 | slot_differs_from_request=true，原要求未被更改 | PASS |
| 5 | 重复提交去重 | case5_duplicate_submit | M01 同请求连续提交两次 | run1=saved，run2=duplicate，drafts.json 仅 1 条 | PASS |
| 6 | 保存失败如实返回 | case6_save_failure | M_SAVE_FAIL @ 11-05 12:00 | draft_status=failed，失败原因可见，草稿文件为空 | PASS |

附加验证：

| 场景 | 示例 | 结果 |
| --- | --- | --- |
| 未过审素材（状态+时长双违规） | case4_unapproved_material（M04） | PASS：rule_risk，2 项违规 |
| 步数上限 → 明确未完成 | case7_step_limit（max_steps=3） | PASS：status=unfinished，未保存草稿，说明原因 |
| 不虚报发布 | 全部示例 | PASS：publish_status 恒为 not_published_draft_only，无"已发布"字样 |

## 两条执行路径（题目要求 ≥2 条不同工具结果导致不同后续动作）

**路径 A（mock，case1）**：query_slot(18:00) 返回**被占用** → 模型调整为查询 19:00 → 空闲 → 保存替代时段草稿 → finish。
见 `examples/case1_slot_conflict/trace.md` 步骤 3-5。

**路径 B（mock，case2）**：check_rules 返回**缺少必填字段 duration_sec** → 模型直接 finish，不调用 save_draft，请求用户补充信息。
见 `examples/case2_missing_info/trace.md`。

真实模型（GLM）同样存在分叉：path1 查询 18:00 被占用后探索 19:00 并保存；path2 检查后立即终止。见 `examples/real-model/`。

## 单元测试（25 项，全部通过）

```bash
py -3 -m pytest tests -q
# 25 passed
```

| 测试文件 | 覆盖 |
| --- | --- |
| tests/test_tools.py（12 项） | 工具级行为：读取/失败、规则检查（违禁词/未过审/超时长/缺字段）、时段查询、保存幂等、占用拒绝、故障注入 |
| tests/test_agent.py（13 项） | Agent 级行为：6 个验收点、步数上限、不虚报发布、硬性要求不被静默更改、无观察时结果为 unknown |

## 真实模型验证（GLM via csu API）

`examples/real-model/` 下 5 条路径，全部通过：

| 路径 | 结果 |
| --- | --- |
| path1_conflict_alternative | 查 18:00 占用 → 查 19:00 空闲 → 保存 19:00 草稿（6 步） |
| path2_missing_info | 检查后立即终止，说明缺失字段（3 步） |
| path3_rule_risk | 发现违禁词即终止（3 步） |
| path4_duplicate_submit | run1 保存 → run2 重复提交返回 duplicate，仅 1 份草稿 |
| path5_save_failure | 保存失败如实返回 failed，未产生草稿 |

## 复现方式

```bash
# 离线示例（无需任何密钥）
py -3 -X utf8 scripts/gen_examples.py

# 真实模型示例（需 .env 配置 OPENAI_API_KEY）
py -3 -X utf8 scripts/gen_real_traces.py

# 单元测试
py -3 -m pytest tests -v
```

每个示例目录的 `trace.md` 即"输入/输出/运行记录"三件套中的运行记录。
