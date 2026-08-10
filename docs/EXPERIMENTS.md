# GoAI 实验记录规范

所有实验必须记录实验编号、运行编号、时间、输入路径与 SHA-256、方法、指标、结论、限制和产物路径。适合提交的小型结果统一存放在 `data/experiments/`；大体积运行产物存放在共享目录 `/home/undefined/Disk/experiments/goai/`，本机可通过被 Git 忽略的 `data/experiments/external_output` 软链接访问，不再创建单独的顶层 `experiments/` 目录。

决策事件实验运行命令：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_decision_event_experiments.py \
  --database data/processed/v1/goai.sqlite \
  --output /home/undefined/Disk/experiments/goai
```

Agent MVP 实验运行命令：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_agent_mvp_experiments.py \
  --database data/processed/v1/goai.sqlite \
  --output /home/undefined/Disk/experiments/goai
```

跨季度状态引擎实验运行命令：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_state_engine_experiments.py \
  --database data/processed/v1/goai.sqlite \
  --output /home/undefined/Disk/experiments/goai
```

Pre-Agent 全链路实验运行命令：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_pre_agent_experiments.py \
  --database data/processed/v1/goai.sqlite \
  --output /home/undefined/Disk/experiments/goai
```

模块化指标与多 Agent 接口实验运行命令：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_modular_decision_experiments.py \
  --dataset /home/undefined/Disk/datasets/goai/processed/v2 \
  --output /home/undefined/Disk/experiments/goai
```

统一数据集硬约束审计：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/run_hard_constraint_audit.py \
  --dataset /home/undefined/Disk/datasets/goai/processed/v2 \
  --output /home/undefined/Disk/experiments/goai/hard_constraint_audit.json
```

每次运行创建独立的 `runs/<run_id>/`，并更新：

- `/home/undefined/Disk/experiments/goai/experiment_registry.json`：机器可读累计实验登记表。
- `/home/undefined/Disk/experiments/goai/实验记录.md`：人工可读累计实验记录。
- `/home/undefined/Disk/experiments/goai/runs/<run_id>/run_summary.json`：单次运行摘要。
- `/home/undefined/Disk/experiments/goai/runs/<run_id>/EXP-*.json`：每项实验的完整记录。
- `/home/undefined/Disk/experiments/goai/runs/<run_id>/EXP-*.csv`：实验明细结果。

历史观察只能作为规则发现和模型假设的证据。没有正式规则确认时，不得把观察到的动作时点、动作顺序或参数关系标记为正式可执行规则。

## 2026-08-07 全规则模板随机比赛与 XLSX 往返实验

- 运行入口：`scripts/generate_and_run_simulated_match.py --all-base-matches --team-count 3 --orders-per-year 4 --seed 20260807`
- 输入：`/home/undefined/Disk/datasets/goai/processed/v2/matches/` 下 14 个现有规则包，优先使用各场 `rules_inferred_v2.json`。
- 方法：每个规则包生成一个随机子规则包、16 条全局订单、3 家企业，运行 20 个季度；随后导出比赛式多 XLSX，并从 XLSX 可见表格回读统一 JSONL。
- 结果：14/14 场完成，42 个企业 XLSX 均含九个预期可见 sheet；企业数和全局订单数往返一致；全部比赛的会计恒等式检查通过。
- 产物：`/home/undefined/Disk/datasets/goai/simulations/SIM_*_seed_*/`；批次摘要为 `/home/undefined/Disk/datasets/goai/simulations/all_template_generation_summary_seed_20260807.json`。
- 限制：旧比赛的父规则仍是推断候选规则，生成结果只能用于模拟、策略测试和数据管线验证，不能作为历史比赛事实或正式训练标签。

## 2026-08-07 高复杂度批次实验（EXP-SIM-LARGE-20260808）

- 运行入口：`scripts/generate_and_run_simulated_match.py --all-base-matches --scale-profile large --seed 20260808 --output-root /home/undefined/Disk/datasets/goai/simulations/large_20260808 --no-round-trip`
- 输入：`/home/undefined/Disk/datasets/goai/processed/v2/matches/` 下 14 个规则模板，优先使用 `rules_inferred_v2.json`。
- 方法：每场使用 24 家企业（LX_XA 使用 27 家）、每年 100 条订单、18% 竞单比例和 20% 规则参数波动；企业策略按 balanced/growth/operations/finance 四类确定性分化，覆盖研发、市场、ISO、广告、采购、生产、交付、贷款、贴现和竞单。
- 结果：14/14 场完成 20 季；总计 339 个企业 XLSX、5,600 条订单、32,731 条事件、1,371 条订单分配、507 条交付、804 条违约；14 场均通过资产负债平衡检查。每场均有 16–23 类事件，订单与事件复杂度显著高于原先的 3 企业/16 订单批次。
- XLSX 抽样回读：对 `SIM_AB_seed_20260808` 执行 `SimulatedCompetitionXlsxImporter`，回读 24 家企业、400 条全局订单、2,581 条事件和 6,192 条报表记录，结构和现金流字段可用。
- 产物：`/home/undefined/Disk/datasets/goai/simulations/large_20260808/all_template_generation_summary_seed_20260808.json`。
- 限制：这些规则、订单、策略、事件、报表和排名均为模拟数据；父规则来自各比赛的推断规则包，不能当作正式裁判规则或历史训练标签。完整私有状态轨迹未默认写入，需使用 `--full-trace` 单独生成。

## 2026-08-10 复杂单企业 Agent 实验（EXP-OWNED-COMPLEX-V1）

- 运行入口：`scripts/run_owned_agent_robustness.py --order-seed 20260810 --opponent-profile conservative --opponent-profile mixed --opponent-profile aggressive --team-count 12 --scenario-count 12`
- 输入：XA 正式参数、796 条 XA 形状随机订单、同一订单种子，分别配置保守、混合和激进对手；每组运行固定基线和复杂滚动 Agent。
- 复杂决策：融资、资格、产能、供应、生产、履约和市场七个动作域；共享柔性线联合排程；短贷、长贷、原料、在建产线、研发、维护和租金现金时点进入风险情景。
- 中间失败 1：复杂规划器未接入主策略，仍存在“有订单只履约”和“第四年禁止扩张”。已删除旧分支。
- 中间失败 2：初始无订单时只买厂房、没有经营闭环，导致 Y5Q1 破产。已加入不读取未来订单的最小启动组合。
- 中间失败 3：柔性线按产品重复计算产能，导致两笔违约。已改为多产品共享产线联合排程，并按最早交期保留库存。
- 中间失败 4：订单风险漏算短贷到期和后续付款，激进对手组破产。已加入完整现金义务调度，并修正慢速产线首批完成窗口。
- 最终结果：复杂 Agent 3 场平均获单/交付为 3.67/3.67，破产率 0%，违约场次比例 0%，最低现金均值 53.67；覆盖 4 种产品、4 个市场和 1 项 ISO 的平均终局资格，并实际使用七个动作域。固定基线平均获单/交付为 2.33/1.00，违约场次比例 100%。
- 主要不足：复杂 Agent 平均得分 70.01，低于固定基线 288.31；平均权益仅 39.33，说明资格投入过宽、利润与权益保留不足。当前实验只证明复杂决策、排程和风险闭环可运行，不证明策略优于人工或基线。
- VPD 验收：`decision_acceptance.py` 已规定相同规则、订单种子、对手、接入时点和初始状态下的 Agent—人工配对比较；硬约束优先，VPD 与 VPD/OE 为离线主指标。旧 VPD/OE 公式尚待 XA 会计口径校准。
- 产物：`data/experiments/owned_agent_complex_v1/results.json`。
