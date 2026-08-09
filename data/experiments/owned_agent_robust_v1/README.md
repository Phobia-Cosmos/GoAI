# 单企业鲁棒 Agent 实验

本目录只评估我们拥有的一家企业。其余 26 家企业是本地不可控对手样本，不代表真实参赛者会使用 GoAI。

- `results.json`：修正订单分配—季度推进—生产—交付动作窗口后的正式 9 组配对结果。
- `results_v0_1_failed.json`：首轮失败结果，保留用于回归和解释交期模型修正，不能代表当前策略。

复现实验：

```bash
PYTHONPATH=src /home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_owned_agent_robustness.py --output data/experiments/owned_agent_robust_v1/results.json
```

实验使用 XA 固定参数，不修改正式参数；订单内容和对手行为均为模拟。完整解释见 [`../../../docs/OWNED_ENTERPRISE_AGENT_SYSTEM.md`](../../../docs/OWNED_ENTERPRISE_AGENT_SYSTEM.md)。
