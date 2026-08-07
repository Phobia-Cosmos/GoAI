# GoAI 数据集

本目录同步的是可公开、可复现的规范化数据和模拟数据，不包含 `origin data` 原始资料目录。

| 子目录 | 内容 | 可信边界 |
| --- | --- | --- |
| `processed/v1/` | SQLite、CSV、数据字典和质量报告 | 历史/测试资料，按记录保留来源等级 |
| `processed/v2/` | 14 场比赛的标准化数据、规则包、事件、回放和审计结果 | XA 较完整；其他比赛含推断规则，不能自动视为正式裁判规则 |
| `simulations/` | 随机规则、订单、状态机事件、报表和比赛式 XLSX | 全部为 `simulated`，只用于沙盘、压力测试和 Agent 验证 |

原始比赛资料仍需通过仓库外的 `origin data/` 提供。数据同步到 GitHub 后，使用者仍应检查 `manifest.json`、`provenance` 和规则绑定状态。
