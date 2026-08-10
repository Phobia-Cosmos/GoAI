# GoAI Pre-Agent 决策内核

Pre-Agent 层是不依赖 LLM、能够独立读取规则和状态、校验动作、推进经营状态、计算指标并比较候选方案的确定性内核。只有该层达到正式就绪，LLM Agent 才能作为工具编排和解释层接入，而不能替代规则、计算或仿真。

## 当前完成情况

| 能力 | 状态 | 版本或证据 |
| --- | --- | --- |
| 源文件清单与可追溯数据 | 完成 | 43 个源文件、37 张标准表 |
| 标准经营事件 | 完成 | 2,167 条事件、33 类动作 |
| Agent 候选动作空间 | 完成 | 20 类候选动作 |
| 题面参数规则包 | 完成 | `rulepack_v0.1` |
| 流程和会计语义规则 | 外部阻塞 | 12 个 blocker |
| 现金、原料、短贷和季度状态 | 实验完成 | `experimental_state_v0.3` |
| BOM、生产周期和产成品 | 实验完成 | `experimental_state_v0.3` |
| 订单交付与应收账款 | 实验完成 | `experimental_state_v0.3` |
| 状态守恒和风险检查 | 完成 | `pre_agent_metrics_v0.1` |
| 基础经营指标 | 完成 | `pre_agent_metrics_v0.1` |
| Pareto 候选方案比较 | 完成 | `pre_agent_kernel_v0.1` |
| 历史最终现金重放 | 完成 | 15/15 队伍一致 |
| 历史完整经营重放 | 外部阻塞 | 600W 正式规则和季度非现金快照缺失 |
| PSS/EPSS/H 正式指标 | 外部阻塞 | 正式公式和会计分配口径缺失 |
| 跨比赛预测验证 | 外部阻塞 | 当前只有一场历史比赛 |

当前状态是 `experimental_ready=true`、`formal_ready=false`。这意味着接口、状态守恒、测试和实验闭环已经可以运行，但不能把实验策略当作正式比赛规则。

## 状态模型

`ExperimentalState` 当前包含：

- 比赛、规则版本、年度、季度和现金。
- 原材料和产成品库存。
- 在途原料订单。
- 在制生产任务。
- 应收账款。
- 短期贷款。
- 生产线实例和产品研发资格。
- 已交付订单。
- 累计收入、采购、加工、管理费和利息。
- 不可变状态 ID 和完整事件日志。

## 已实现状态转移

- 原料下单后按题面提前期到货。
- 原料到货后进入库存并按实验策略付款。
- 短贷借入、按季度简单折算利息并在到期时偿还。
- 按 BOM 校验并消耗原料或半成品。
- 校验产品资格、生产线存在性和产线占用。
- 支付加工费并建立在制任务。
- 按产线生产周期完成并进入产成品库存。
- 交货时扣减产成品并确认实验性收入。
- 现金订单即时回款，账期订单形成应收并到期回款。
- 季度推进时结算管理费、原料、应收和短贷。
- 任何结算导致现金为负时原子拒绝，原状态不变。

## 基础指标

指标服务当前输出现金、原料库存价值、产成品直接成本价值、在制品直接成本代理值、应收款、短贷、追踪资产、净流动头寸、下一季度承诺、下一季度回款、现金缓冲、累计收入、现金贡献代理值以及风险标记。

这些指标不等于正式会计报表、PSS、EPSS 或最终竞赛评分。存货计价和收入成本配比未确认前，只能使用清晰命名的实验代理指标。

## 命令

查看完整性清单：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent pre-agent-status
```

运行生产—交付—应收时间线：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent state-simulate \
  --state-json data/examples/production_ready_state.json \
  --timeline-json data/examples/production_delivery_timeline.json
```

计算状态指标：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent state-metrics \
  --state-json data/examples/production_ready_state.json
```

比较候选方案：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent compare-state-plans \
  --state-json data/examples/production_ready_state.json \
  --candidates-json data/examples/pre_agent_candidates.json
```

## 无法由当前资料自动补齐的内容

- 历史 600W 数据的正式规则版本。
- 581 条订单与具体比赛的绑定。
- 广告、询单、选单和竞单算法。
- 贷款额度、申请资格和精确结息时点。
- 折旧、税费、损失、年末结转和完整会计分录。
- 违约、特别贷款、注资、破产和最终排名规则。
- PSS/EPSS/H 的正式公式与成本分配口径。
- 跨比赛预测和权重泛化验证所需的更多比赛数据。

这些内容已经作为 RulePack blocker 和 Pre-Agent 外部阻塞项登记。系统不会自行编造规则将其标记为完成。
