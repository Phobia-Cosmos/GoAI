# GoAI

GoAI 是面向企业经营比赛的可审计辅助决策系统。它以规则包、结构化事件和确定性财务状态机为核心，在人工确认前生成并比较多个可执行经营方案；LLM 仅是可选的规划与解释层，不负责财务真值或动作合法性。

完整项目现状和 Agent 路线图见 [docs/PROJECT_STATUS_AND_AGENT_PLAN.md](docs/PROJECT_STATUS_AND_AGENT_PLAN.md)。

## 本仓库包含什么

- `src/goai_data/`：数据导入、规则、状态机、回放、指标、候选决策和模拟环境。
- `scripts/`：数据构建、规则冻结、回放、约束审计、实验和模拟比赛生成入口。
- `tests/`：自动测试。
- `examples/`：可复现的示例输入和完整模拟比赛样例。
- `docs/`：项目状态、最终目标和实施路线图。
- `experiments/`：实验记录规范。

## 外部数据

比赛原始资料不提交到 Git；可公开的规范化数据和模拟数据已同步到仓库的 `data/`。当前开发机的 `origin data` 仍是指向旧资料位置的外部软链接，并被 `.gitignore` 排除。

面向后续在线 Agent 的 XA 真实/模拟同构数据入口为 [`data/agent_ready/v1/xa/`](data/agent_ready/v1/xa/)，运行闭环和部分可观测信息边界见 [`docs/ONLINE_AGENT_SYSTEM_DESIGN.md`](docs/ONLINE_AGENT_SYSTEM_DESIGN.md)。仅控制我方一家企业的鲁棒滚动决策实现与实验结果见 [`docs/OWNED_ENTERPRISE_AGENT_SYSTEM.md`](docs/OWNED_ENTERPRISE_AGENT_SYSTEM.md)。

在另一台机器上，请将原始资料放入 `origin data/`，或建立同名软链接；仓库内的 `data/` 已包含可复现数据，也可以按 [DATA_LAYOUT.md](DATA_LAYOUT.md) 改为外部共享路径。新仓库不依赖 `Others` 的 Git 仓库历史即可运行源码、测试和已同步的数据。

## 快速验证

```bash
cd /home/undefined/Desktop/GoAI
/home/undefined/Disk/python-envs/goai-py312/bin/python -m pytest -q
```

## 可信边界

所有数据均需区分 `observed`、`derived`、`inferred`、`simulated` 和 `missing`。只有已确认规则下的 `observed + derived` 数据可作为正式回放基准；推断和模拟数据仅用于候选仿真、压力测试和接口验证。
