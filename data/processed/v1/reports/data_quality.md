# GoAI 数据质量报告

生成时间：2026-08-04T12:20:36+08:00

## 摘要

| 项目 | 数量 |
| --- | ---: |
| `source_files` | 36 |
| `workbook_sheets` | 198 |
| `nonempty_workbook_cells` | 54126 |
| `active_teams` | 15 |
| `empty_team_exports` | 3 |
| `orders` | 581 |
| `cash_flow_events` | 2026 |
| `structured_action_events` | 2167 |
| `blocking_rule_gaps` | 12 |
| `quality_error_count` | 1 |

## 质量检查

| 严重度 | 代码 | 数量 | 说明 | 细节 |
| --- | --- | ---: | --- | --- |
| warning | `empty_team_exports` | 3 | 企业导出文件存在但没有经营流水。 | ZY01, ZY12, ZY18 |
| info | `action_event_normalization` | 0 | 现金流动作标准化及结构化事件映射检查。 | events=2167; fully_parameterized=1202 |
| warning | `rule_pack_blocking_gaps` | 12 | RulePack 中尚未由可用题面确认、会阻止完整仿真的规则缺口。 | simulation_ready=false |
| info | `cash_flow_continuity` | 0 | 现金流水逐笔余额连续性校验。 |  |
| info | `balance_sheet_identity` | 0 | 资产总计与负债和所有者权益总计校验。 |  |
| info | `public_team_financial_consistency` | 0 | 公共年度报表与企业报表交叉校验。 | compared=3225 |
| info | `public_team_advertising_consistency` | 0 | 公共广告巡盘与企业广告表交叉校验。 | compared=1800 |
| error | `cross_competition_initial_capital_conflict` | 1 | 历史企业初始注资与题面初始资本不一致，已保持批次隔离。 | historical=[600.0]; rules=[710.0] |

## 表记录数

| 表 | 记录数 |
| --- | ---: |
| `source_manifest` | 36 |
| `workbook_inventory` | 198 |
| `workbook_cells` | 54126 |
| `competition_rules` | 1 |
| `rule_financing` | 3 |
| `rule_financing_terms` | 4 |
| `rule_factories` | 3 |
| `rule_production_lines` | 4 |
| `rule_markets` | 5 |
| `rule_iso` | 2 |
| `rule_materials` | 4 |
| `rule_products` | 5 |
| `rule_bom` | 9 |
| `rule_packs` | 1 |
| `rule_gaps` | 14 |
| `action_definitions` | 33 |
| `action_aliases` | 50 |
| `action_events` | 2167 |
| `order_catalog` | 581 |
| `annual_advertising` | 2160 |
| `annual_financial_metrics` | 3225 |
| `annual_production_lines` | 654 |
| `annual_market_leaders` | 30 |
| `teams` | 18 |
| `team_cash_flows` | 2026 |
| `team_financial_metrics` | 3870 |
| `team_advertising` | 1800 |
| `team_orders` | 222 |
| `team_material_orders` | 14 |
| `team_material_inventory` | 54 |
| `team_product_inventory` | 29 |
| `team_receivables` | 25 |
| `team_loans` | 48 |
| `team_qualifications` | 129 |
| `team_factories` | 33 |
| `team_production_lines` | 109 |
| `test_cash_flow_events` | 141 |

## 使用限制

- `historical_600_unknown_rule`、`zhejiang_8th_710` 与 `order_catalog_unbound` 保持隔离，未确认前不得跨批次连接训练或重放。
- `workbook_cells` 是保真兜底表；业务分析优先使用对应的标准化长表。
- 金额统一为万元；保留 `raw_value` 或来源坐标以支持复核。
