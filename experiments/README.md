# GoAI 实验记录规范

所有实验必须记录实验编号、运行编号、时间、输入路径与 SHA-256、方法、指标、结论、限制和产物路径。实验结果存放在共享生成物目录 `/home/undefined/Disk/experiments/goai/`，本目录中的 `output` 软链接指向该位置。

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

- `output/experiment_registry.json`：机器可读累计实验登记表。
- `output/实验记录.md`：人工可读累计实验记录。
- `output/runs/<run_id>/run_summary.json`：单次运行摘要。
- `output/runs/<run_id>/EXP-*.json`：每项实验的完整记录。
- `output/runs/<run_id>/EXP-*.csv`：实验明细结果。

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
