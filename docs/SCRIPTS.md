# 命令行脚本索引

`scripts/` 不是数据目录或文档目录，而是从终端调用系统能力的薄入口。业务规则、状态机、Agent 和数据处理实现都位于 `src/goai_data/`；脚本只解析参数、调用模块并写出结果。为了保持目录简单，所有入口继续放在同一个 `scripts/` 目录，不再拆出更多子目录。

## 数据构建与规则整理

| 脚本 | 作用 |
| --- | --- |
| `build_multimatch_dataset.py` | 从 `data/original/` 构建 14 场标准化 v2 数据集 |
| `build_xa_agent_dataset.py` | 生成 XA 真实/模拟同构的 Agent-ready 数据 |
| `enrich_partial_events.py` | 对可由证据确定的部分事件补充参数 |
| `freeze_xa_rules.py` | 冻结 XA 正式规则来源和可审计校验 |
| `reconstruct_xa_intermediate.py` | 重建 XA 的季度现金、资格、资产、贷款和订单路径 |
| `generate_complete_match_example.py` | 生成 `data/examples/complete_match_v1/` 完整模拟样例 |

## 回放、模拟与验证

| 脚本 | 作用 |
| --- | --- |
| `run_all_match_replays.py` | 对全部标准比赛生成规则候选和确定性历史回放 |
| `run_xa_fixed_match.py` | 使用 XA 固定参数和随机订单运行完整比赛 |
| `run_xa_historical_profiles.py` | 使用 27 家历史策略运行检查点、条件和竞争三种模式 |
| `generate_and_run_simulated_match.py` | 从任意比赛规则模板生成随机规则、订单和完整比赛 |
| `validate_traditional_xa.py` | 用 XA 数据验证传统订单与沙盘候选规则 |
| `run_hard_constraint_audit.py` | 审计统一数据集和回放结果的硬约束 |

## Agent 与实验运行

| 脚本 | 作用 |
| --- | --- |
| `run_decision_event_experiments.py` | 决策事件标准化实验 |
| `run_agent_mvp_experiments.py` | 早期 Agent 候选生成与排序实验 |
| `run_state_engine_experiments.py` | 跨季度状态转移实验 |
| `run_pre_agent_experiments.py` | Pre-Agent 全链路实验 |
| `run_modular_decision_experiments.py` | 模块化指标和多 Agent 接口实验 |
| `run_owned_agent_robustness.py` | 我方单企业对未知对手和订单种子的鲁棒性实验 |

常规开发只需运行测试。只有重建数据、生成新模拟批次或复现实验时才需要直接调用这些脚本：

```bash
cd /home/undefined/Desktop/GoAI
PYTHONPATH=src /home/undefined/Disk/python-envs/goai-py312/bin/python -m pytest -q
```
