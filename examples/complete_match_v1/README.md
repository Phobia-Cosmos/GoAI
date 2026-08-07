# 完整比赛数据样例 v1

这是一套结构完整、数值自洽、但明确标记为 `synthetic_reference` 的五年比赛样例。它用于展示后续需要寻找、导出和整理的数据形态，不代表 AB、CA、CB、CD、CE、EA、EB、EC、EF、OP 中任何一场真实比赛，也不能加入历史训练数据。

## 先看哪个文件

只想一次看到全部内容，读取 `complete_match.json`。需要按模块开发或人工检查时，读取同目录拆分文件：

| 文件 | 内容 | 主要使用者 |
| --- | --- | --- |
| `manifest.json` | 数据集身份、来源组、用途限制、文件哈希 | 数据层 |
| `rule_pack.json` | 中文十簇观察规则、缺失规则和模拟假设 | 所有组件 |
| `global_context.json` | 20 家企业、60 条全局订单、订单分配和 20 季公共状态 | 决策 Agent、VPD |
| `enterprise_timeline.json` | 目标企业初始状态、逐事件现金、20 个季度快照 | 报表 Agent |
| `reports.json` | 五年综合费用表、利润表和资产负债表 | 报表 Agent、VPD |
| `analytics.json` | 20 季 PSS、VPD/OE、U1/U2/U3 和耦合示例 | VPD、决策 Agent |
| `decision_cycles.json` | 每季信息集、三个候选、选择、人工确认、提交事件和结果 | 决策 Agent、审计 |
| `validation_report.json` | 完整性、现金连续性、报表恒等式和外键检查 | 测试与审计 |

## 一次决策怎样流动

以 `decision_cycles.json` 中任一季度为例：

1. `base_state_id` 指向报表状态内核已经确认的期初状态。
2. `information_set` 只引用当时可见的 RulePack、订单和公共信息，并关联一个 VPD 指标包。
3. `candidates` 保存保守、平衡和激进三个方案及其沙盒预测，不只保存最终选择。
4. `selected_candidate_id` 和 `selection_reason` 记录选择依据；硬约束违规方案不能被提交。
5. `human_confirmation` 记录人工确认状态。
6. `submitted_event_ids` 指向 `enterprise_timeline.json` 中真正驱动状态机的标准事件。
7. `outcome.state_id` 指向事件重放后的季度快照，供下一轮决策和 VPD 诊断使用。

因此两个已有 Agent 的正确关系是：报表 Agent 先维护状态和财报，VPD 读取该状态生成指标，决策 Agent 使用状态、规则、订单和指标产生候选，再调用报表状态机的沙盒分支验证；确认后的事件回到报表 Agent，形成新状态。

## 来源等级

所有关键对象带 `provenance.status`：

| 状态 | 含义 | 可否作为正式训练事实 |
| --- | --- | --- |
| `observed` | 源文件或平台直接观察 | 规则绑定和来源完整时可以 |
| `derived` | 从观察值按版本化公式确定性计算 | 公式审计通过时可以 |
| `inferred` | 从不完整历史或规则启发式重建 | 默认不可以，应单独评估 |
| `simulated` | 接口样例、候选推演或情景数据 | 不可以 |
| `missing` | 当前资料中没有 | 不可以，也不能用其他比赛参数静默填充 |

本样例中完整事件、订单、对手状态和决策均为 `simulated`。600W 初始资本、10W 季度管理费、厂房购价和容量、市场/产品/ISO 开发费用与周期、自动线和柔性线完工投入等字段，来自中文十簇共同观察指纹，但仍不等于正式规则原文。

## 现在应按什么方向找数据

优先寻找 `rule_pack.json` 的 `blocking_gaps`，并为每份资料记录比赛 ID、规则版本、文件哈希、导出主体、导出时间和可见阶段：

1. 正式竞赛规程、操作手册和完整题面。
2. 统一初始状态，包括现金之外的厂房、产线、库存、资格和贷款。
3. 每个阶段允许的动作、前置条件、失败提示和自动结算顺序。
4. 与 AB 至 OP 对应的赛前完整订单池，以及广告、询单、选单、平局和市场老大规则。
5. 原料价格、提前期、产品 BOM、加工费、生产周期、转产和折旧规则。
6. 长短贷、贴现、应收、税、违约、破产、注资和最终评分规则。
7. 同一企业每季动作日志、前后状态快照、年度三张报表和最终排名。
8. 同场其他企业在当时确实公开的信息，不能只保留赛后汇总而忽略可见时点。

## 重新生成

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python \
  scripts/generate_complete_match_example.py
```

生成器会覆盖本目录中的 JSON 文件并重新执行现金、报表和外键检查。它使用固定生成版本时间，因此相同代码应得到相同组件哈希。
