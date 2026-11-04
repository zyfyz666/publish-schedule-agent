# 素材审核与发布排期 Agent

小影校招 AI Agent 方向笔试项目。一个基于 **ReAct 循环**（模型选择动作 → 执行工具 → 观察结果 → 调整或结束）的发布排期 Agent：核对素材信息与审核规则、检查发布时段冲突、保存**待用户确认的排期草稿**——只保存草稿，绝不发布。

## 快速开始

```bash
# 1. 安装依赖（仅 pytest）
pip install -r requirements.txt

# 2. 离线运行（默认 Mock 模型，无需任何 API 密钥）
py -3 -m src.cli --material M01 --date 2026-11-05 --time 18:00

# 3. 运行单元测试（25 项）
py -3 -m pytest tests -v

# 4. 一键生成全部验收示例（examples/ 下 7 个案例，无需密钥）
py -3 -X utf8 scripts/gen_examples.py
```

> Windows 下若 `python` 不可用请用 `py -3`。Linux/Mac 直接 `python3 -m src.cli ...`。

接入真实模型（可选）：复制 `.env.example` 为 `.env`，设置 `LLM_PROVIDER=openai` 并填入 OpenAI 兼容端点与密钥。

## 命令行用法

```bash
# 处理单个排期任务
py -3 -m src.cli --material M01 --date 2026-11-05 --time 18:00

# 从任务文件运行，并把 结果/trace 写入目录
py -3 -m src.cli --input examples/case1_slot_conflict/input.json --out output

# 列出待处理素材
py -3 -m src.cli --scan

# 限制步数（超限返回明确的未完成状态）
py -3 -m src.cli --material M01 --date 2026-11-05 --time 18:00 --max-steps 3

# 使用真实模型
py -3 -m src.cli --material M01 --date 2026-11-05 --time 18:00 --llm openai
```

## 目录结构

```
├── src/
│   ├── agent.py      # ReAct 主循环 + 观察推导最终结果
│   ├── tools.py      # 4 个业务工具（素材/规则/时段/保存草稿）
│   ├── llm.py        # MockLLM（离线）+ OpenAICompatibleLLM（真实模型）
│   ├── trace.py      # 决策 trace 渲染（Markdown 表格）
│   ├── runner.py     # 组件装配与 .env 加载
│   └── cli.py        # 命令行入口
├── data/             # 素材、审核规则、已有排期（合成数据）
├── tests/            # pytest 单元测试（25 项）
├── examples/         # 输入/输出/运行记录（验收证据，见 examples/README.md）
│   └── real-model/   # 真实模型（GLM）运行记录
├── scripts/          # 示例生成脚本
├── docs/             # 01 需求 / 02 方案 / 03 评测 / 04 AI 使用 / 05 复盘
└── requirements.txt
```

## 验收点 → 证据对照

| 验收点 | 示例（examples/） |
| --- | --- |
| 正常排期 | case1_slot_conflict（保存链路 + 冲突处理） |
| 素材信息缺失 | case2_missing_info（缺 duration_sec → 阻断并转人工） |
| 规则风险 | case3_rule_risk（违禁词）、case4_unapproved_material |
| 时段冲突与替代建议 | case1（18:00 被占 → 建议 19:00，原要求不被静默更改） |
| 重复提交去重 | case5_duplicate_submit（两次提交仅 1 份草稿） |
| 保存失败如实返回 | case6_save_failure |
| 步数上限 → 明确未完成 | case7_step_limit（unfinished + 原因） |
| 真实模型一致性 | examples/real-model/（GLM，5 条路径） |

## 设计要点（详见 docs/）

1. **ReAct 循环**：模型选动作 → 执行工具 → 观察写回 → 模型调整或结束（`src/agent.py`）；
2. **防虚报**：模型只选动作，最终结论由工具观察推导；`publish_status` 恒为 `not_published_draft_only`；
3. **不静默改硬性要求**：替代时段草稿显式标记 `slot_differs_from_request` 并要求用户确认；
4. **幂等去重**：同素材+同日期+同原始要求时段重复提交，只保留一份草稿并返回 duplicate；
5. **失败显式**：保存失败返回 `failed`，步数超限返回 `unfinished` + 原因，均不假装成功。

## 环境变量（仅真实模型需要）

见 `.env.example`。`LLM_PROVIDER=mock`（默认）完全离线；`openai` 需提供 OpenAI 兼容端点与密钥。
