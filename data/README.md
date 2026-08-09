# GoAI 数据集

本目录同步的是可公开、可复现的规范化数据和模拟数据，不包含 `origin data` 原始资料目录。

| 子目录 | 内容 | 可信边界 |
| --- | --- | --- |
| `processed/v1/` | SQLite、CSV、数据字典和质量报告 | 历史/测试资料，按记录保留来源等级 |
| `processed/v2/` | 14 场比赛的标准化数据、规则包、事件、回放和审计结果 | XA 较完整；其他比赛含推断规则，不能自动视为正式裁判规则 |
| `simulations/` | 随机规则、订单、状态机事件、报表和比赛式 XLSX | 全部为 `simulated`，只用于沙盘、压力测试和 Agent 验证 |
| `agent_ready/v1/xa/` | XA 真实与模拟数据的同构决策时点视图 | `observation` 可供 Agent 使用；`offline_labels` 仅供训练评估，禁止在线泄漏 |

原始比赛资料仍需通过仓库外的 `origin data/` 提供。数据同步到 GitHub 后，使用者仍应检查 `manifest.json`、`provenance` 和规则绑定状态。

当前 Agent 数据整理方式和时间边界见 [`agent_ready/v1/xa/README.md`](agent_ready/v1/xa/README.md)。

固定使用 XA 正式参数、可完整运行 20 个季度的标准模拟比赛见 [`simulations/xa_fixed_v1/`](simulations/xa_fixed_v1/README.md)。其他 `simulations/` 批次可能随机扰动过规则，只用于跨规则压力测试。
