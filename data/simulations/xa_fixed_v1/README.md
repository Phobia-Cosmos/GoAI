# 固定 XA 规则完整模拟比赛

`SIM_XA_FIXED_seed_20260809/` 是当前 Agent 设计的标准全局环境样本。它使用真实 XA `rules.json` 中的全部参数，不随机修改初始资金、管理费、税率、违约罚金、厂房、产线、产品、市场、ISO、物料或评分公式；随机种子只影响全局订单内容、订单竞争和基线 Agent 行为。

XA 原始资料不能唯一确定的结算顺序、折旧年限、资产处置比例、竞单支付方式和未选订单处理方式，被固定为 `rules.json.financial_rules` 中的传统沙盘候选服务。这些服务使环境可以完整运行，但不应被称为已经确认的正式裁判细节。

当前比赛配置与结果：

| 项目 | 数值 |
| --- | ---: |
| 企业/Agent | 27 |
| 季度 | 20 |
| 随机订单 | 796 |
| 年度订单分布 | Y2=169、Y3=172、Y4=214、Y5=241 |
| 竞单 | 24 |
| Agent 观测/动作/反馈 | 各 540 |
| 订单分配与交付 | 48 / 48 |
| 违约 | 0 |
| 年度报表 | 135 |
| 最终有效排名 | 27 |
| 会计平衡 | 通过 |
| 比赛式 XLSX 导出和回读 | 通过 |

核心文件角色：

| 文件 | 视角与用途 |
| --- | --- |
| `rules.json` | XA 固定参数和候选结算服务 |
| `global_orders.jsonl` | 全局环境真值；Agent 只能看到当前已发布且未分配的子集 |
| `observations.jsonl` | 每个 Agent 每季决策前可见的完整私有状态、公开订单 ID 和合法动作 |
| `actions.jsonl` | 基线 Agent 提交的动作包 |
| `feedback.jsonl` | 环境对每个动作包返回的奖励、事件、破产与会计信息 |
| `quarter_states.jsonl` | 初始状态和每季结束后的紧凑状态，共 567 条 |
| `trace.jsonl` | 全局环境每季的联合动作和联合反馈，供裁判推进和多 Agent 分析 |
| `events.jsonl`、`reports.jsonl`、`states.jsonl` | 完整事件、年度三表和终局状态 |
| `results.json` | 最终排名、得分和破产结果 |
| `competition_xlsx/` | 与比赛资料相似的规则、订单、结果和 27 个企业 XLSX |
| `xlsx_imported/` | XLSX 回读后的统一 JSONL，用于验证导入导出闭环 |
| `validation.json` | 规则一致性、20 季完整性、观测隔离、订单形状、会计平衡和终局检查 |

复现命令：

```bash
PYTHONPATH=src /home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_xa_fixed_match.py
```

环境拥有所有企业和全局订单，Agent 只收到自身私有状态以及按发布时间筛选的公共订单。`available_orders` 已从私有状态中移除，首年所有观测的公开订单数量均为零，未来订单不会泄漏给 Agent。
