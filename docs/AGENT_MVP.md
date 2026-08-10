# GoAI Agent MVP v0.3

项目整体目标、当前数据与规则状态、已有模块关系和 Agent 后续阶段见：[GoAI 项目现状、目标与 Agent 实施路线图](PROJECT_STATUS_AND_AGENT_PLAN.md)。

当前实现是一个确定性、可审计的实验性决策 Agent。它不依赖 LLM，可以读取规则状态和经营快照、列出候选动作、校验动作、执行现金沙盒仿真并比较候选方案。

由于 `zhejiang_8th_rules_v1` 仍有 blocker 级规则缺口，Agent 强制保持 `formal_commit_allowed=false`。当前结果只能用于实验、规则发现和接口验证，不能直接提交为正式经营动作。

## 当前能力

- 查看 RulePack 状态和未解决缺口。
- 正式模式下自动拒绝不完整规则包。
- 实验模式下列出 20 类 Agent 候选动作。
- 从历史队伍现金流或 710W 测试方案生成不可变状态快照。
- 校验标准动作名称、Agent 控制权、必要参数和即时现金安全。
- 模拟多步现金变化，并在中途现金不足时拒绝方案。
- 比较多套候选方案，第一版按“最大化最低现金，再最大化期末现金”排序。
- 所有工具返回状态、违规、警告、前置条件、建议工具、快照 ID、规则版本、引擎版本和追踪 ID。
- 使用版本化实验策略推进季度，处理原料提前期、到货入库、到货付款、短贷到期和季度管理费。
- 通过 Pre-Agent 内核处理 BOM、生产周期、产成品、订单交付、应收回款、状态守恒、指标和 Pareto 候选比较。

## CLI

查看规则状态：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent status
```

列出实验性候选动作：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent actions --mode experimental
```

验证正式模式会被规则缺口阻断：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent actions --mode formal
```

读取历史队伍最终现金快照：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent snapshot --team-id ZY02
```

读取测试方案指定季度快照：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent snapshot \
  --scenario-id 9line_p1_p4_2937 \
  --year 3 \
  --quarter 2
```

运行多步现金沙盒：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent simulate \
  --team-id ZY02 \
  --actions-json data/examples/agent_actions.json
```

比较候选方案：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent advise \
  --team-id ZY02 \
  --candidates-json data/examples/agent_candidates.json
```

运行跨季度状态仿真：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-agent state-simulate \
  --timeline-json data/examples/state_timeline.json
```

状态时间线支持：

```json
[
  {
    "type": "action",
    "action_type": "material_order",
    "parameters": {"materials": {"R1": 2, "R3": 1}}
  },
  {
    "type": "action",
    "action_type": "short_loan_borrow",
    "parameters": {"principal_wan": 100, "term_quarters": 4}
  },
  {"type": "advance_quarter"}
]
```

## 当前边界

- 历史队伍只有现金可以按事件时间重建；库存、贷款、产线等表是导出时最终快照。
- 现金模拟尚未覆盖资格、BOM、库存、产能、交期、会计结转和对手行为。
- 对缺少状态转移规则的动作，Agent 返回 `needs_input`，不会自行编造计算规则。
- 股东注资、竞单成功、税费、还款和到期结算等事件不在 Agent 动作空间。
- 当前候选排序只是现金安全基线，不代表利润、权益或综合评分最优。
- `experimental_state_v0.2` 假定原料到货时付款、短贷年利率按季度简单折算并在到期时还本息、管理费在季度推进时扣除；这些假设尚不是正式规则。
