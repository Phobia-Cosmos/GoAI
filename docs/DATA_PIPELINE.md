# GoAI 数据处理管道

本管道只读解析项目中的 `.xls`、`.xlsx`、`.docx` 和 Markdown 测试现金流，生成适合查询、分析和后续规则引擎使用的标准数据集。它不会修改原始资料。

## 输出位置

规范数据存放在：

```text
/home/undefined/Disk/datasets/goai/processed/v1/
```

项目中的 `data/` 是仓库内统一数据目录；原始资料通过 `data/original/` 软链接接入，大体积共享副本仍可由脚本参数指向 `/home/undefined/Disk/datasets/goai`。

```text
data/processed/v1/
├── csv/                         # 每张标准表一个 UTF-8 BOM CSV
├── metadata/
│   ├── data_dictionary.csv      # 字段、类型、单位和说明
│   ├── schemas.json             # 表级结构与记录数
│   └── rulepack_zhejiang_8th_rules_v1.json # 可供规则引擎加载的 RulePack v0.1
├── reports/
│   ├── data_quality.md          # 人工可读质量报告
│   └── run_summary.json         # 机器可读运行摘要
└── goai.sqlite                  # 包含全部标准表和常用索引
```

## RulePack 与结构化事件

规则与经营动作已进一步整理为以下核心表：

| 表 | 用途 |
| --- | --- |
| `rule_packs` | 规则包版本、数据绑定和是否可用于正式仿真 |
| `rule_financing_terms` | 长贷、短贷及 1–2/3–4 季贴现的分档条款 |
| `rule_gaps` | 尚未由题面确认的流程、状态转移和会计规则缺口 |
| `action_definitions` | 跨历史和测试数据统一的标准动作语义 |
| `action_aliases` | 原始中英文动作名称到标准动作的映射 |
| `action_events` | 历史与测试现金流统一后的结构化事件及参数 JSON |

`rule_packs.simulation_ready = 0` 表示当前规则包还不能用于正式完整仿真。`action_events` 中的历史事件是规则发现和重放证据，不代表其动作语义已经由 710W 题面确认。

查询示例：

```sql
SELECT * FROM rule_packs;

SELECT domain, title, severity
FROM rule_gaps
WHERE status = 'unresolved';

SELECT team_id, year, quarter, canonical_action, parameters_json, cash_effect_wan
FROM action_events
WHERE event_source = 'historical_cash_flow'
ORDER BY team_id, sequence;
```

## 运行

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-data
```

指定其他目录：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/goai-data \
  --root /home/undefined/Desktop/GoAI \
  --output /home/undefined/Disk/datasets/goai/processed/v1
```

运行测试：

```bash
cd /home/undefined/Desktop/GoAI
/home/undefined/Disk/python-envs/goai-py312/bin/pytest -q
```

## 使用建议

- 快速查询和跨表连接优先使用 `goai.sqlite`。
- 与 Excel 或人工审核协作时使用 `csv/`。
- 任何分析前先读取 `source_manifest`，只连接相同且已确认的 `competition_id + rule_version`。
- `workbook_cells` 保存所有非空单元格，是尚未完成业务映射时的保真兜底表；正常分析优先使用标准业务表。
- 所有 `*_wan` 字段单位为万元；年份和季度拆成独立整数列。
- 每张业务表都尽可能保留 `source_id`、`source_path`、`source_sheet`、`source_row` 或 `source_cell`。
- 只有 `rule_packs.simulation_ready = 1` 的规则包才允许进入正式仿真；当前 `zhejiang_8th_rules_v1` 明确保持为不可执行的部分规则包。

## 当前批次

| `competition_id` | 含义 | 使用限制 |
| --- | --- | --- |
| `historical_600_unknown_rule` | 1–6 年公共数据和 ZY 企业明细 | 规则版本尚未确认，可做同批次分析，暂不与 710W 题面重放 |
| `zhejiang_8th_710` | 710W 题面、测试方案和测试现金流 | 可用于规则解析及测试方案校验 |
| `order_catalog_unbound` | 581 条赛前订单 | 与上述比赛的归属尚未确认，不自动连接 |
| `design_reference` | 论文、PSS/商分/Agent 设计资料 | 不作为经营事实表 |

## 随机比赛与比赛式 XLSX

完整候选财务沙盘可以从 `processed/v2/matches/` 中任意比赛的 `rules_inferred_v2.json`（若不存在则回退 `rules.json`）生成新比赛。生成规则保留父规则包、来源比赛、随机种子和参数变化记录，且全部标记为 `simulated`，不会覆盖历史比赛数据。

生成一场以 AG 为模板的比赛：

```bash
cd /home/undefined/Desktop/GoAI
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/generate_and_run_simulated_match.py \
  --base-match AG \
  --match-id SIM_AG_DEMO \
  --team-count 8 \
  --orders-per-year 30 \
  --seed 20260807
```

为当前数据集中的全部比赛规则包各生成一场：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/generate_and_run_simulated_match.py \
  --all-base-matches \
  --team-count 3 \
  --orders-per-year 4 \
  --seed 20260807
```

### 规模档位与高复杂度批次

随机比赛现在支持 `small`、`standard`、`large`、`stress` 四个档位；显式传入 `--team-count`、`--orders-per-year`、`--auction-ratio` 或 `--variability` 时会覆盖档位默认值。默认档位已调整为 `large`，用于避免只有少量企业和订单的低复杂度实验。

| 档位 | 企业数（默认） | 每年订单 | 竞单比例 | 规则参数波动 | 初始现金倍率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `small` | 4 | 15 | 8% | 10% | 1.0 |
| `standard` | 20（按来源比赛企业数覆盖） | 60 | 12% | 15% | 1.15 |
| `large` | 24（LX_XA 为 27） | 100 | 18% | 20% | 3.0 |
| `stress` | 32 | 160 | 25% | 25% | 4.0 |

例如重新生成全部 14 个规则模板的高复杂度比赛，并保留比赛式 XLSX：

```bash
/home/undefined/Disk/python-envs/goai-py312/bin/python scripts/generate_and_run_simulated_match.py \
  --all-base-matches \
  --scale-profile large \
  --seed 20260808 \
  --output-root /home/undefined/Disk/datasets/goai/simulations/large_20260808 \
  --no-round-trip
```

该批次产物为 `/home/undefined/Disk/datasets/goai/simulations/large_20260808/`，包含 14 场比赛、339 个企业 XLSX、5,600 条全局订单和 32,731 条状态机事件。每场仍固定运行 20 个季度；破产企业会保持破产状态并推进时钟到 Y5Q4，便于统一比较。生成内容全部标记为 `simulated`，不代表历史事实或正式比赛标签。

大型批次默认写入紧凑 `trace.jsonl` 和 `quarter_states.jsonl`，保留动作、奖励、结算信息和关键财务快照，避免完整私有状态快照造成磁盘膨胀。需要调试级完整轨迹时增加 `--full-trace`；完整 XLSX 往返可在单场或抽样场次上去掉 `--no-round-trip` 验证。

每场的 `competition_xlsx/` 目录都采用统一结构：

```text
competition_xlsx/
├── 企业数据/
│   ├── SIM_XX01.xlsx
│   ├── SIM_XX02.xlsx
│   └── ...
├── SIM_XX比赛规则.xlsx
├── SIM_XX订单详情.xlsx
├── SIM_XX最终排名和破产信息.xlsx
└── manifest.json
```

每个企业工作簿包含 `企业信息`、`库存信息`、`银行贷款`、`研发认证`、`厂房与生产线`、`订单信息`、`现金流量表`、`三张报表`、`广告投放` 九个可见 sheet，与 XA 企业导出的主要布局一致。`xlsx_imported/` 是从这些 XLSX 可见表格重新解析得到的统一 JSON/JSONL，可直接进入后续分析、replay 和 Agent 训练前处理。隐藏的 `_GOAI_META` 只保存规则身份和来源标记，不替代表格数据。
