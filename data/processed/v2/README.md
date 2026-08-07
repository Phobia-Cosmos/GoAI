# GoAI 中文企业经营比赛统一数据集 v2

本目录将 13 场历史导出和 1 场省赛完整资料统一为同一结构。所有赛场都具有相同文件名和字段结构；内容完整度通过 `provenance`、`coverage_scope`、`observed_complete` 和 `quality.json` 明确表达。旧比赛缺少正式规则原件和赛前全局订单池，现已生成面向仿真的逐场重建规则集与未分配订单；这些记录明确标记为 `inferred` 或 `simulated`，不会冒充官方事实。

## 企业事件流

主事件流来自每个企业工作簿的 `现金流量表` sheet，第 4 行开始依次为 `ID、动作、资金、余额、时间、备注`。`events.jsonl` 是其标准化结果；`订单信息`、`厂房与生产线`、`研发认证`、`库存信息` 和三张报表是事件结果的状态与审计证据。

## 每场比赛目录

| 文件 | 用途 |
| --- | --- |
| `manifest.json` | 比赛身份、来源文件、哈希和完整性声明 |
| `rules.json` | 正式规则、观察指纹、候选规则和缺口 |
| `teams.jsonl` | 企业元数据及导出状态 |
| `events.jsonl` | 企业经营事件流 |
| `global_orders.jsonl` | XA 完整观测订单池；旧场次为已分配订单加模拟未分配订单 |
| `annual_public.jsonl` | 年度广告、公共报表、市场老大和生产线巡盘 |
| `reports.jsonl` | 企业年度报表和企业广告 |
| `final_states.jsonl` | 比赛结束或破产时状态与评分输入 |
| `quarter_states.jsonl` | 每队固定 20 个季度现金切片 |
| `results.json` | 排名、评分与破产时间 |
| `raw_cells.jsonl` | 全部 XLS 非空单元格保真长表 |
| `quality.json` | 现金连续性、订单、覆盖率和形状检查 |

## 赛场概览

| match_id | 企业数 | 经营事件 | 订单总数 | 模拟订单 | 订单覆盖 | 观测完整 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| AB | 20 | 3762 | 494 | 204 | observed_allocated_plus_simulated_unassigned | false |
| AG | 19 | 1625 | 184 | 55 | observed_allocated_plus_simulated_unassigned | false |
| CA | 20 | 3947 | 495 | 173 | observed_allocated_plus_simulated_unassigned | false |
| CB | 20 | 3698 | 492 | 164 | observed_allocated_plus_simulated_unassigned | false |
| CD | 20 | 4034 | 494 | 160 | observed_allocated_plus_simulated_unassigned | false |
| CE | 20 | 4311 | 493 | 153 | observed_allocated_plus_simulated_unassigned | false |
| EA | 20 | 3719 | 494 | 189 | observed_allocated_plus_simulated_unassigned | false |
| EB | 20 | 4251 | 492 | 142 | observed_allocated_plus_simulated_unassigned | false |
| EC | 20 | 3841 | 493 | 203 | observed_allocated_plus_simulated_unassigned | false |
| EF | 20 | 3426 | 494 | 250 | observed_allocated_plus_simulated_unassigned | false |
| OP | 20 | 3497 | 492 | 221 | observed_allocated_plus_simulated_unassigned | false |
| ZY | 18 | 2026 | 415 | 193 | observed_allocated_plus_simulated_unassigned | false |
| ZZ | 16 | 1853 | 416 | 193 | observed_allocated_plus_simulated_unassigned | false |
| LX_XA | 27 | 3787 | 796 | 0 | complete_observed_pool | true |

## 使用顺序

先用 XA 建立可审计的规则状态机和报表重放基准，再用旧赛场训练动作识别、异常检测、VPD/PSS 指标和行为模式。旧场次的模拟未分配订单只适合训练接口、压力测试和候选策略，不可用于评估历史参赛队当时真实可见的机会集合。
