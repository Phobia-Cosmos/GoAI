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

## 2026-08-11 XA 企业群体与得分差距校准（EXP-XA-POPULATION-V1）

- 运行入口：`scripts/run_xa_population_calibration.py --seeds 20260811 20260812 20260813`。
- 固定输入：XA 正式参数、27 家企业、20 个季度、796 条经验形状订单；订单生成保留真实联合分布但清除终局归属、状态、分数和破产标签。
- 中间失败 1：首版策略在 Y1Q1 同时启动过多资格、厂房、产线和原料，27 家全部早期破产。已把经营顺序改为融资、预演期初自动结算、再规划经营动作。
- 中间失败 2：严格排程器只分配约 59–104 单，产线没有扩张依据。已加入年度批量选择、企业稳定偏好和滚动积压上限；过度宽松时交付仍不足并产生违约，因此部署用单企业 Agent 继续保留严格鲁棒排程器。
- 中间失败 3：全扩张群体在严格负权益规则下仍几乎全部破产。最终采用 18 家现金安全存续群体和 9 家高风险扩张群体，先校准真实风险分布，不把未来企业标签写入在线观测。
- 中间失败 4：在安全群体上直接增加小额长贷、第二条 P2 产线、P2 生产和额外申领后，单种子从 18 家存续退化为 0 家存续，交付从 23 降至 21。该改动已回退，证明产能投资必须与已锁定的可交付利润联合优化，不能只按现金阈值扩张。
- 三种子结果：每场均为 18 家存续、9 家破产，所有会计平衡，动作拒绝为 0。存续企业平均得分 276.43、权益 211.02、发展潜力 31；平均分配 96.67 单、交付 22 单、未分配 699.33 单。
- 真实目标：存续企业得分 1569.39、权益 584.22、发展潜力 149.67；分配 561 单、交付 544 单、未分配 235 单。
- 结论：风险分布已稳定对齐，但订单吞吐、产能和资产规模仍是主要策略瓶颈。下一实验应先提高订单组合选择和履约产能，再评估权益、得分和 VPD，不能通过虚增现金或修改正式评分参数制造接近结果。
- 产物：`data/experiments/xa_population_calibration_v1/summary.json` 及三个种子的 `calibration_report.json`；种子 `20260811` 另保留完整观测、动作、反馈、状态和事件轨迹。

## 2026-08-11 单企业六专业 Agent 协同实验（EXP-XA-COLLABORATIVE-V3）

- 运行入口：`scripts/run_xa_population_calibration.py --survivor-policy collaborative --output-root data/experiments/xa_collaborative_calibration_v3 --seeds 20260811 20260812 20260813`。
- 决策结构：资金、资格、产能、供应履约、订单组合和风险批评六个专业 Agent 共同控制一家企业；共享黑板、第一次能力预演、订单组合、最终完整动作包重放、环境反馈回流。
- 已修复问题：订单候选之间未累计占用共享产能；先乘产线数再向下取整导致慢速线容量虚增；自动线安装期未进入订单可交付窗口；每单使用紧急采购导致利润流失；广告优先规则未进入订单组合；资产扩张、融资和履约没有经过同一最终风险重放。
- 三种子结果：每场均为 18 家存续、9 家破产；会计全部平衡，动作拒绝为 0。存续企业平均得分 303.29、权益 231.64、发展潜力 30.85；每场获单 96、交付 39.67，获单后交付率 41.31%。
- 相对上一版：存续平均得分提高 26.86，权益提高 20.62，每场交付增加 17.67，交付率提高约 18.55 个百分点；获单减少 0.67，因为不可整批交付的容量高估已被删除。
- 真实差距：存续平均得分仍差 1266.10，权益差 352.58；平均获单 3.56 对比真实 20.78，平均交付 1.47 对比真实 20.15，交付率 41.31% 对比真实 96.97%。
- 结论：协同规划显著提高了订单兑现和经营结果，并保持真实破产分布，但尚未达到真实经营规模。下一实验必须优先提高可兑现订单吞吐和异质对手覆盖，再由利润驱动产线、市场、ISO 和自有厂房扩张。
- 产物：`data/experiments/xa_collaborative_calibration_v3/summary.json`；模块说明为 `docs/COLLABORATIVE_AGENT_DESIGN.md`。

## 2026-08-11 可点击平台与协同 Agent v0.3（EXP-XA-COLLABORATIVE-V4）

- 运行入口：`scripts/run_xa_population_calibration.py --survivor-policy collaborative --output-root data/experiments/xa_collaborative_calibration_v4 --seeds 20260811 20260812 20260813`。
- 平台入口：`scripts/run_web_platform.py --host 127.0.0.1 --port 8765`；支持单人对 Agent、多人对 Agent、纯用户、纯 Agent、同步季度结算和终局完整记录导出。
- 本轮修复：选单冲突后按同一轮候选队列继续尝试；统一单项/双项 ISO 资格；把本季期初到货计入履约可用库存；按积压滚动普通采购；已获订单的生产和应急物料不再被风险模块当作可选扩张删除；短贷按正式四季度期限保留为终局负债；年末折旧导致负权益时立即由环境判定破产。
- 策略变化：我方一家企业由六专业 Agent 共享黑板；轻资产启动，在获单后按产品积压批量建设自动线；订单组合可使用有界未来产能，但最终仍由环境的建设、生产、交期、现金和破产转移裁决。
- 三种子均值：存续/破产 14.33/12.67；存续平均得分 490.88、全体平均得分 246.55、权益 212.83、发展潜力 129.41；每场获单 302.67、交付 235、违约 31.67、交付率 77.65%；平均完成产线 5.52，动作拒绝 0，会计全部平衡。
- 相对 v0.2：获单为 3.15 倍、交付为 5.92 倍，交付率提高 36.34 个百分点，发展潜力由 30.85 提高到 129.41，存续平均分由 303.29 提高到 490.88。
- 真实差距：真实获单/交付为 561/544、交付率 96.97%、权益 584.22、发展潜力 149.67、存续平均分 1569.39。当前仍少交付 309 单/场，且多破产约 3.67 家；不能称为已贴近全部评分。
- 产物：`data/experiments/xa_collaborative_calibration_v4/summary.json`、三个种子的校准报告和首个种子的完整比赛轨迹；平台说明为 `docs/CLICKABLE_COMPETITION_PLATFORM.md`。

## 2026-08-11 协同 Agent v0.6 与晚期失败压力场（EXP-XA-COLLABORATIVE-V8）

- 基准入口：`scripts/run_xa_population_calibration.py --survivor-policy collaborative --output-root data/experiments/xa_collaborative_calibration_v8 --seeds 20260811 20260812 20260813`。
- 本轮因果修正：基础厂房由全租赁改为目标数量购买后再租赁；成品库存进入订单组合容量；冲突回退只能复用同产品且交期不早于主订单的容量；成长型企业首年两线，其他企业一线；P2→P4、P3→P5 半成品链进入生产；到期短贷可按规则覆盖实际到期义务；风险预演加入年末折旧。
- 指标口径修正：产品、市场、ISO、已完成产线和自有厂房均改为只对存续企业计算，与真实 XA 聚合资产口径一致；订单指标仍以全部 27 家企业为分母。
- 三种子基准均值：17.33 家存续、9.67 家破产；存续平均得分 811.28、全体平均得分 520.34、权益 337.58、发展潜力 136.71；每场获单 354、交付 273.33、违约 41、获单后交付率 77.23%；存续企业平均产品/市场/ISO 为 3.00/5.00/2.00，平均完成产线 6.43、自有厂房 2.31。全部会计平衡，动作拒绝为 0。
- 相对 v0.3：存续数增加 3，得分提高 320.40，权益提高 124.75，获单增加 51.33，交付增加 38.33，产线增加 0.91；交付率因获单扩张略降约 0.42 个百分点。
- 压力入口：`scripts/run_xa_population_calibration.py --survivor-policy collaborative_late_failure --output-root data/experiments/xa_late_failure_stress_v2 --seeds 20260811 20260812 20260813`。
- 压力场含义：9 家高风险对手先用同一协同闭环经营，再按稳定的企业级触发点增加租赁线和广告，由状态机在 Y4–Y5 判定是否破产；不读取真实企业未来路径或终局标签。三种子均值为 17.33 家存续、349.33 单获单、299.33 单交付、85.68% 交付率，平均得分 647.06、权益 273.76。
- 结论：v0.6 已使存续结构、发展潜力、市场、ISO 和自有厂房接近真实数量级，并把订单规模继续推高；平均交付仍只有真实的 50.25%，基准交付率仍低于真实约 19.74 个百分点。下一实验必须实现订单分配后的同季度条件经营阶段，以及 4–8 季度的产线/BOM/现金联合搜索。
- 产物：`data/experiments/xa_collaborative_calibration_v8/summary.json`、`data/experiments/xa_late_failure_stress_v2/summary.json` 及各自三个种子的校准报告；每组首个种子保存完整轨迹。

## 2026-08-12 协同 Agent v0.7 模块化消融（EXP-XA-COLLABORATIVE-V12）

- 正式入口：`scripts/run_xa_population_calibration.py --survivor-policy collaborative --output-root data/experiments/xa_collaborative_calibration_v12 --seeds 20260811 20260812 20260813`。
- v0.7 默认保持 v0.6 的六专业共享黑板、联合状态机预演、同产品订单回退、BOM 履约和风险裁剪；新增 `allow_prospective_new_cell` 可选接口，默认关闭，用于比较“是否允许在已有产线外预留一个基础产品单元”。
- 三种子均值：17.33 家存续、9.67 家破产；存续平均得分 811.28、权益 337.58、发展潜力 136.71；每场获单 354、交付 273.33、获单后交付率 77.23%；平均完成产线 6.43、自有厂房 2.31；动作拒绝 0、会计全部平衡。
- 真实 XA 对照：18/9 家存续/破产，存续平均得分 1569.39、权益 584.22、发展潜力 149.67，每场获单/交付 561/544，获单后交付率 96.97%。v0.7 达到真实的得分 51.69%、权益 57.78%、发展潜力 91.34%、平均获单 63.10%、平均交付 50.25% 和交付率 79.64%。
- 消融结论：统一手工线、一次性扩张融资、无条件预生产和无门槛新产品单元均未被保留；它们或提高破产，或降低终局权益。后续应实现订单分配后同季度条件经营，以及 4–8 季度联合搜索。
- 产物：`data/experiments/xa_collaborative_calibration_v12/summary.json`；协同设计、指标定义和开关说明见 `docs/COLLABORATIVE_AGENT_DESIGN.md`。
- 试验记录：`xa_collaborative_calibration_v9` 组合启用新产品单元和 Q2 单条自动线融资，均值降至存续 17.33、得分 724.74、权益 298.88，回退；`v10` 仅保留无门槛新单元，均值为得分 785.77、权益 326.61、获单 358.67、交付 281.33，回退；`v11` 将新单元限制到 P1–P3 后均值为得分 773.05、权益 322.01、获单 359.33、交付 280.33，仍回退。`v12` 正式基准关闭该开关并恢复 v0.6 结果，证明消融策略没有污染默认线上策略。

## 2026-08-12 双阶段协同 Agent v0.8（EXP-XA-COLLABORATIVE-V15）

- 环境时序：该历史实验新增可选 `post_allocation_phase`。每季度先同步提交融资、资格、资产、广告和订单组合，环境统一解决冲突并公开实际获单；同一季度再提交基于真实在手订单的融资、扩产、采购、生产和交付，最后才执行违约、财务结算与季度推进。旧单阶段模式默认不变，历史重放保持兼容；当时的 Web 实验版默认启用双阶段，当前 v0.8 页面已改为年度规划与季度单次提交，此条仅记录实验演进。
- 多 Agent 协作：第二阶段由资金、产能、履约和风险批评模块重新读取同一企业的全部实际在手订单，按交期、产品、BOM、库存、物料、产线、现金和权益形成联合动作包；不是对单张订单作孤立决策。
- v13 只启用分配后履约：三种子均值为 21.33 家存续，存续得分 1051.20、权益 470.10、获单 364、交付 356.67、交付率 97.99%、完成产线 4.75。它证明原 77.23% 交付率的主要问题是决策时序，但获单规模仍受未来产能限制。
- v14 在双阶段中允许更有界的未来产品产能槽位：三种子均值为 21.67 家存续，得分 1106.00、权益 485.38、获单 394.67、交付 383、交付率 97.03%、完成产线 5.24。该修改同时提高吞吐、权益和得分，因此保留。
- v15 再允许产能模块在实际获单后当季扩厂建线：三种子均值为 19.67 家存续，存续得分 1142.49、权益 465.78、发展潜力 136.76、获单 423、交付 412.67、交付率 97.55%、完成产线 6.93。相对 v12，得分提高 40.83%，权益提高 37.98%，获单提高 19.49%，交付提高 50.98%，交付率提高 20.32 个百分点。
- 真实差距：真实 XA 为 18 家存续、得分 1569.39、权益 584.22、发展潜力 149.67、获单/交付 561/544、交付率 96.97%、完成产线 8.83。v15 的交付率已达到真实数量级并略高 0.58 个百分点，但平均获单和交付仅达到真实的 75.40% 和 75.86%，权益为 79.73%，得分为 72.80%，产线为 78.50%；不能称为全部达标。
- 被拒绝探针：第一年用 250–450 万元长贷预建 3–4 条线使单种子存续降至 14 家且权益下降；把企业/订单随机偏好权重扩大四倍虽增加获单，但权益从 484.93 降至 427.94；两项均回退。受限新产品单元在双阶段下只增加约 11 单，未解除主瓶颈，仍保持默认关闭。
- 产物：`data/experiments/xa_collaborative_calibration_v13/summary.json`、`xa_collaborative_calibration_v14/summary.json` 和 `xa_collaborative_calibration_v15/summary.json`。v15 第一个种子保留完整可审计轨迹，另两个种子保存校准报告。

## 2026-08-12 协同 Agent v0.8.1 权益增量修正（EXP-XA-COLLABORATIVE-V16）

- 诊断：真实 XA 与 v15 已获订单的单均直接毛利几乎相同，分别为 109.29 和 108.09 万元，毛利率约 57%；权益差并不是 Agent 只拿低价值订单。第五年报表中真实存续企业销售收入/毛利均值为 1642.67/968.89，v15 为 1248.05/569.57，说明差距主要来自少交付约 122 单和履约补救成本。
- 修正：到期订单使用紧急成品补货时，旧逻辑只比较“紧急采购成本”与“收入加避免的违约罚款”，漏掉了随交付结转的已有库存账面成本。v16 改为按 `订单收入 + 避免的违约罚款 - 已有库存账面成本 - 紧急采购成本` 计算真实增量权益；只有结果非负才紧急补货并交付。
- 三种子结果：平均 19.67 家存续；存续平均得分 1177.77、全体平均分 858.64、权益 481.42、发展潜力 135.96；每场获单 421.67、交付 410.67、违约 7，交付率 97.3%；平均完成产线 6.83、负债 1177.69。全部会计平衡，动作拒绝为 0。
- 相对 v15：存续结构不变，存续平均得分提高 35.28，权益提高 15.64，全体平均分提高 26.13，平均负债下降 8.16；每场平均少交付 2 单，因为 Agent 不再用亏损性紧急补货维持表面交付率。交付率仍与真实 96.97% 同一水平。
- 相对真实：权益、得分、平均获单、平均交付、交付率分别达到真实的 82.40%、75.05%、75.16%、75.49% 和 100.38%。交付质量已达标，剩余主差距仍是可盈利订单吞吐和约两条产线的规模差。
- 订单漏斗审计：单种子 112161 次可见订单评估中，56282 次因已有承诺超过候选产能被拒，44237 次因资格不符，4360 次因保守毛利不足；952 个主订单槽位最终分配 439 单。已验证并拒绝全自动理论容量、2/3 容量折扣、统一/混合手工线、三产品启动、扩大普通原料库存、无门槛新产品单元、跨产品候补和仅新获单才扩产等方案，它们均降低权益、存续或交付。
- 产物：`data/experiments/xa_collaborative_calibration_v16/summary.json` 和三个种子的完整校准报告；种子 20260811 保留完整轨迹。

## 2026-08-13 协同 Agent v0.9 可执行产能与即时生产修正（EXP-XA-COLLABORATIVE-V17）

- 正式入口：`scripts/run_xa_population_calibration.py --survivor-policy collaborative_late_failure --post-allocation-phase --allow-prospective-new-cell --output-root data/experiments/xa_collaborative_calibration_v17 --seeds 20260811 20260812 20260813`。中断后可用相同参数加 `--summarize-existing` 从已完成报告重建多种子汇总，不重新模拟。
- 获单诊断：v16 的 112161 次订单评估中，56203 次被旧产能门槛拒绝、44416 次资格不足；950 个申领槽位只获 439 单。已获订单中约 75% 只有一个申领者，平均竞争者约 1.38，因此主因不是竞单冲突，而是 Agent 把当前季度、到期季度、在制品和安装完成后的可执行产能算少了。
- 状态机一致性修正：订单 Agent 按每条线的安装完成时点、忙碌任务、生产周期、现有成品和比赛终局计算可执行批次；供应 Agent 不再把自动线已即时入库的产品再次计入在制品；P2→P4、P3→P5 按组件拓扑先生产上游，并把一季度产线的即时产出写回同一动作包的规划库存，随后仍由 `FullFinancialDynamics` 独立重放与裁决。
- 策略修正：网页推荐 Agent 和协同对手默认允许一个有界 P1–P3 新产品单元，前提是已有资格、现金和权益达到门槛；它不是免费产能，获单后仍必须真实融资、建厂、建线、采购和生产。实验脚本继续保留开关以便消融。
- 三种子正式均值：20.33 家存续、6.67 家破产；存续平均得分 1536.90、全体平均得分 1156.08、权益 619.36、发展潜力 142.66；每场获单 497.67、交付 464.33、违约 16.33，平均获单 18.43、平均交付 17.20，获单后交付率 93.26%；平均完成产线 7.97、自有厂房 2.21。全部会计平衡，动作拒绝为 0。
- 相对真实 XA：存续平均得分达到 97.93%，全体平均得分 110.50%，权益 106.01%，发展潜力 95.32%，平均获单 88.71%，平均交付 85.36%，交付率达到真实的 96.18%。评分和权益已进入真实数量级，但获单仍少 63.33 单/场，交付少 79.67 单/场，存续多 2.33 家；不能描述为完全复刻真实 XA。
- 被拒绝探针：仅按获单后的产品级积压扩产使单种子获单降到 378、交付率降到 94.18%；P4/P5 生命周期硬上限虽把交付率提到 96.44%，但获单和存续得分降到 478 与 1315.68；按交期提前复用未来产能使存续降到 16 家、交付率降到 90.78%。三项均未保留。
- 产物：`data/experiments/xa_collaborative_calibration_v17/summary.json`、三个种子的校准报告和种子 20260811 的完整可审计轨迹。
