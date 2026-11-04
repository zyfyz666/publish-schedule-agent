# 02 方案设计

## 总体架构

```
任务输入
   │
   ▼
┌─────────────────────────────────────────────┐
│                ReActAgent                    │
│                                             │
│   ┌─────────┐    ┌─────────┐    ┌────────┐  │
│   │   LLM   │───▶│  动作   │───▶│  工具  │  │
│   │ 选动作  │    │ (JSON)  │    │ 执行   │  │
│   └─────────┘    └─────────┘    └───┬────┘  │
│         ▲                           │       │
│         │      ┌────────────┐       │       │
│         └──────│ 观察结果   │◀──────┘       │
│                │ 写回状态快照 │               │
│                └────────────┘               │
└─────────────────────────────────────────────┘
   │
   ▼
final_result（全部由工具观察结果推导）
```

核心循环（题目硬性要求）：**模型选择动作 → 执行工具 → 观察结果写回状态 → 模型根据观察调整下一步或结束**。

## 关键设计决策

### 1. 原生实现，不依赖 Agent 框架

工具只有 4 个、状态简单（快照字典即可），引入框架（LangChain 等）只会增加理解成本和不可控依赖。手写 ReAct 循环约 100 行，每一步都可见、可测、可复盘。

### 2. LLM 双实现，默认离线可跑

- `MockLLM`：确定性策略状态机，根据观察结果决定动作，离线可复现全部验收点；
- `OpenAICompatibleLLM`：真实模型（OpenAI 兼容协议，JSON 输出），用于验证同一套流程在真模型下同样成立。

评测代码、单元测试全部跑 Mock；`examples/real-model/` 提供真实模型运行记录。切换只需 `LLM_PROVIDER=openai`。

### 3. 防虚报：模型只选动作，结论由观察推导

`build_final_result()` 不信任模型的 finish summary，而是从**工具观察结果快照**推导最终结论：

- 素材不存在 → 来自 `get_material` 的失败观察；
- 信息缺失 → 来自素材字段与规则的比对；
- 规则风险 → 来自 `check_rules` 返回的违规列表；
- 草稿状态（saved/duplicate/failed）→ 来自 `save_draft` 的观察。

模型无法声称"保存成功"或"已发布"——`publish_status` 恒为 `not_published_draft_only`。

### 4. 重复提交去重（幂等）

`save_draft` 的幂等键为 **(material_id, date, requested_time)**：同一素材对同一日期+同一原始要求时段重复提交，无论 Agent 第二次选择了哪个替代时段，都返回 `duplicate` 并指向已有草稿，不产生第二份记录。

> 设计取舍：最初按 (material_id, date, time) 去重，真实模型测试中暴露了绕过路径——模型换了替代时段就绕过了去重。改为按"原始要求"去重后，语义与验收点一致（同一硬性请求只保留一份草稿）。

### 5. 硬性要求不被静默更改

时段被占用时，Agent 查询相邻整点时段、保存**替代时段草稿**，但：

- `requested_slot` 原样保留；
- `slot_differs_from_request=true` 显式标记；
- 草稿 note 记录待确认原因；
- `needs_user_confirmation=true`，未经用户确认不生效。

### 6. 失败路径显式建模

- 工具失败：观察返回 `ok=false`，模型可见，可调整或终止；
- 保存失败：`save_draft` 返回 `status=failed`，final_result 中 `draft_status=failed` 并附失败原因；
- 步数超限：`status=unfinished` + `unfinished_reason`，草稿状态为 `not_saved`，不假装完成。

## 模块说明

| 模块 | 职责 |
| --- | --- |
| `src/tools.py` | 4 个业务工具：get_material / check_rules / query_slot / save_draft；草稿幂等与故障注入 |
| `src/llm.py` | MockLLM（离线策略）+ OpenAICompatibleLLM（真实模型）；统一输出 Decision{thought, action, args} |
| `src/agent.py` | ReActAgent 主循环；AgentContext 状态快照；build_final_result 观察推导 |
| `src/trace.py` | 每步观察摘要 + trace.md 渲染（决策表格 + 最终结果） |
| `src/runner.py` | .env 加载、组件装配 |
| `src/cli.py` | 命令行入口（--scan / 单任务 / --out 输出三件套） |

## 工具清单

| 工具 | 输入 | 输出 |
| --- | --- | --- |
| get_material | material_id（可空=列表） | 素材元数据 / 失败原因 |
| check_rules | material_id | passed + violations[]（规则名+说明） |
| query_slot | date, time | available / occupied_by |
| save_draft | material_id, date, time, requested_time, note | status: saved/duplicate/failed + draft |

## 安全与边界

- 步数上限（默认 10，可配 `--max-steps`），超限返回 `unfinished` 并说明原因；
- 真实模型仅通过 HTTP JSON 协议调用，无代码执行、无文件系统自由访问；
- 系统提示中写明硬性边界（不发布、不改硬性要求、失败如实报告）；
- API 密钥只从 `.env` 读取（已 gitignore），代码与示例中不含真实密钥。
