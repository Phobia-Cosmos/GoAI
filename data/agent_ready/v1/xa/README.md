# XA Agent-ready 数据集

本目录把真实 XA 历史比赛和基于 XA 的模拟比赛组织成同一种“决策时点转换”格式。底层标准化文件仍保留在 `data/processed/` 和 `data/simulations/`，这里仅保存可复现索引和面向 Agent 的无泄漏视图，不复制大文件。

```text
xa/
├── catalog.json
├── real/
│   ├── manifest.json
│   └── transitions.jsonl
└── simulated/
    ├── SIM_XA_FIXED_seed_20260809/
    └── SIM_XA_INITIAL_seed_20260809/
        ├── manifest.json
        └── transitions.jsonl
```

真实与模拟的每条 `transitions.jsonl` 均包含以下字段：

| 字段 | 含义 | 能否输入在线 Agent |
| --- | --- | --- |
| `observation` | 决策开始时本企业可见状态、已发布公共信息和规则引用 | 可以 |
| `offline_labels.historical_decision_events` / `action_bundle` | 历史企业或模拟基线在该时点采取的动作 | 不可以，仅训练和分析 |
| `offline_labels.realized_feedback` | 动作完成后的状态变化 | 当前时点不可以，执行动作后才成为下一次输入 |
| `offline_labels.terminal_result` | 最终排名、得分、权益和破产结果 | 不可以，仅轨迹级评价 |
| `excluded_from_observation` | 明确禁止泄漏的字段类别 | 不可以 |

真实 XA 数据包含 27 家企业、20 个季度、共 540 个连接/决策时点。真实数据中的季度私有状态目前只能稳定给出期初现金以及本企业历史事件引用，不能假装已经恢复完整的历史资产负债状态。在线接入时，比赛系统必须额外提交接入时刻的完整本企业快照，包括现金、贷款、应收款、库存、在制品、厂房、生产线、研发、市场、认证、已获订单和未履约义务。

固定 XA 模拟数据同样包含 27 个 Agent、20 个季度和 540 个转换。它直接使用完整的无泄漏 `AgentObservation`，并保存动作与环境反馈；动作由现金约束启发式基线产生，不是最优动作标签。底层规则参数与 XA 一致，但无法从正式资料唯一确认的结算过程仍属于固定候选实现。

生成命令：

```bash
PYTHONPATH=src /home/undefined/Disk/python-envs/goai-py312/bin/python scripts/build_xa_agent_dataset.py
```

数据使用必须遵守时间边界：在 `Y3Q2` 接入时，只能使用本企业截至 `Y3Q2` 接入点之前的操作历史、接入时完整本企业状态、已经发布的公共信息和 XA 规则。其他企业私有操作、尚未公布的信息、订单最终归属、未来反馈和终局成绩均只能放在离线评估器中。
