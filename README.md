# StratPilot

StratPilot是面向企业经营沙盘的可审计人机协同决策系统。它以每场独立规则包、结构化事件和确定性财务状态机为核心，在人工确认前生成并比较多个带理由的可执行经营方案；LLM 仅是可选的语言理解与解释层，不负责财务真值或动作合法性。

新的产品定位、每场规则生成、人机差异、反事实评估和脱敏发布方案见 [`docs/PRODUCT_SYSTEM_DESIGN.md`](docs/PRODUCT_SYSTEM_DESIGN.md)；当前可交付版本和内部基准对照见 [`docs/CURRENT_VERSION_SUMMARY.md`](docs/CURRENT_VERSION_SUMMARY.md)；初赛提交与保密边界见 [`docs/COMPETITION_SUBMISSION_SECURITY.md`](docs/COMPETITION_SUBMISSION_SECURITY.md)。

## 目录

- `src/goai_data/`：数据导入、规则、状态机、回放、指标、候选决策和模拟环境。
- `scripts/`：薄命令行入口；业务实现都在 `src/`，脚本清单见 [`docs/SCRIPTS.md`](docs/SCRIPTS.md)。
- `tests/`：自动测试。
- `docs/`：全部项目级说明、架构、数据布局、实验规范和 Agent 设计。
- `data/`：原始资料入口、规范化数据、模拟数据、实验结果和样例数据。

## 外部数据

比赛原始资料不提交到 Git；可公开的规范化数据和模拟数据已同步到仓库的 `data/`。当前开发机的 `data/original` 是指向旧资料位置的外部软链接，并被 `.gitignore` 排除。

面向后续在线 Agent 的 XA 真实/模拟同构数据入口为 [`data/agent_ready/v1/xa/`](data/agent_ready/v1/xa/)，运行闭环和部分可观测信息边界见 [`docs/ONLINE_AGENT_SYSTEM_DESIGN.md`](docs/ONLINE_AGENT_SYSTEM_DESIGN.md)。仅控制我方一家企业的鲁棒滚动决策实现与实验结果见 [`docs/OWNED_ENTERPRISE_AGENT_SYSTEM.md`](docs/OWNED_ENTERPRISE_AGENT_SYSTEM.md)。

XA 历史结果现已精确复现 18 家正式比分与排名、9 家破产企业及其破产季度；“结果回放”和“仅靠动作重算的前向因果模拟”之间的能力边界见 [`docs/XA_REPLAY_FIDELITY.md`](docs/XA_REPLAY_FIDELITY.md)。

XA 的 540 个中途状态、贷款/折旧/税费/生产批次逐项反推以及据此完成的前向模拟器校准，见 [`docs/XA_INTERMEDIATE_RECONSTRUCTION.md`](docs/XA_INTERMEDIATE_RECONSTRUCTION.md)。

27 家企业历史决策路径、四类策略画像、检查点辅助重建与竞争压力模式，见 [`docs/XA_HISTORICAL_STRATEGY_REPLAY.md`](docs/XA_HISTORICAL_STRATEGY_REPLAY.md)。

在另一台机器上，请将原始资料放入 `data/original/`，或建立同名软链接；仓库内其余 `data/` 内容已包含可复现数据，也可以按 [`docs/DATA_LAYOUT.md`](docs/DATA_LAYOUT.md) 改为外部共享路径。新仓库不依赖 `Others` 的 Git 仓库历史即可运行源码、测试和已同步的数据。

## 快速验证

```bash
cd /home/undefined/Desktop/GoAI
/home/undefined/Disk/python-envs/goai-py312/bin/python -m pytest -q
```

## 启动可点击比赛

```bash
cd /home/undefined/Desktop/GoAI
PYTHONPATH=src /home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_web_platform.py --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765` 后可以创建单人对 Agent、多人对 Agent、纯用户或纯 Agent 比赛，选择聚合异质、晚期扩张压力、协同、保守基线或启发式对手；全部经营动作均可点击加入联合决策包。完整用法、接口和部署边界见 [`docs/CLICKABLE_COMPETITION_PLATFORM.md`](docs/CLICKABLE_COMPETITION_PLATFORM.md)，最新六专业 Agent 与真实 XA 指标对比见 [`docs/COLLABORATIVE_AGENT_DESIGN.md`](docs/COLLABORATIVE_AGENT_DESIGN.md)。

## 可信边界

所有数据均需区分 `observed`、`derived`、`inferred`、`simulated` 和 `missing`。只有已确认规则下的 `observed + derived` 数据可作为正式回放基准；推断和模拟数据仅用于候选仿真、压力测试和接口验证。
