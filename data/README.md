# GoAI 数据集

本目录统一保存所有数据入口。可公开、可复现的规范化数据和模拟数据会提交；`original` 只是指向仓库外原始资料的本地软链接，不会提交。

| 子目录 | 内容 | 可信边界 |
| --- | --- | --- |
| `processed/v1/` | SQLite、CSV、数据字典和质量报告 | 历史/测试资料，按记录保留来源等级 |
| `processed/v2/` | 14 场比赛的标准化数据、规则包、事件、回放和审计结果 | XA 较完整；其他比赛含推断规则，不能自动视为正式裁判规则 |
| `simulations/` | 随机规则、订单、状态机事件、报表和比赛式 XLSX | 全部为 `simulated`，只用于沙盘、压力测试和 Agent 验证 |
| `agent_ready/v1/xa/` | XA 真实与模拟数据的同构决策时点视图 | `observation` 可供 Agent 使用；`offline_labels` 仅供训练评估，禁止在线泄漏 |
| `simulations/xa_historical_profiles_v1/` | XA 27 家企业历史策略的检查点、条件和竞争重建 | 检查点模式使用未来信息，只用于离线校准；竞争模式用于鲁棒压力测试 |
| `experiments/owned_agent_robust_v1/` | 我方单企业对多订单种子和未知对手组合的鲁棒性实验 | 对手与订单均为本地模拟；只用于我方策略验证，不是历史事实 |
| `experiments/external_output/` | 指向共享大体积实验目录的本地软链接 | 不进入 Git，其他机器可按需重建 |
| `examples/` | 小型输入样例和完整模拟比赛数据 | 用于接口演示与测试，不是历史事实 |
| `original/` | 原始比赛资料和历史参考项目的本地入口 | 仓库外只读资料，不进入 Git |

原始比赛资料仍需通过 `data/original/` 提供。数据同步到 GitHub 后，使用者仍应检查 `manifest.json`、`provenance` 和规则绑定状态。

当前 Agent 数据整理方式和时间边界见 [`agent_ready/v1/xa/README.md`](agent_ready/v1/xa/README.md)。

固定使用 XA 正式参数、可完整运行 20 个季度的标准模拟比赛见 [`simulations/xa_fixed_v1/`](simulations/xa_fixed_v1/README.md)。其他 `simulations/` 批次可能随机扰动过规则，只用于跨规则压力测试。

Y1Q1 含 36 个公共订单和 18 个随机预分配订单的显式场景扩展见 [`simulations/xa_initial_orders_v1/`](simulations/xa_initial_orders_v1/README.md)。真实 XA、固定模拟和初始订单模拟的结果对比见 [`../docs/XA_REAL_VS_SIMULATION_ANALYSIS.md`](../docs/XA_REAL_VS_SIMULATION_ANALYSIS.md)。

仅控制我方一家企业的鲁棒滚动 Agent、信息边界和 9 组配对结果见 [`../docs/OWNED_ENTERPRISE_AGENT_SYSTEM.md`](../docs/OWNED_ENTERPRISE_AGENT_SYSTEM.md)。
