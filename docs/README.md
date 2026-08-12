# GoAI 文档索引

项目级说明统一放在本目录。数据目录内保留的少量 `README.md` 是与数据一同分发的清单和可信边界，不是另一套项目文档。

| 文档 | 用途 |
| --- | --- |
| `PROJECT_STATUS_AND_AGENT_PLAN.md` | 项目目标、当前进度和 Agent 总路线 |
| `SYSTEM_ARCHITECTURE.md` | 系统组件、数据契约和协作关系 |
| `DATA_LAYOUT.md` | 仓库内外的数据存储规则 |
| `DATA_PIPELINE.md` | 原始 XLS/XLSX/DOCX 到规范数据的处理方式 |
| `SCRIPTS.md` | `scripts/` 中全部命令行入口的用途 |
| `EXPERIMENTS.md` | 实验记录规范和历史批次 |
| `MODULAR_AGENT_DESIGN.md` | 模块化指标与多 Agent 接口设计 |
| `PRE_AGENT.md` | Pre-Agent 原型说明 |
| `AGENT_MVP.md` | 早期决策 Agent MVP 说明 |
| `ONLINE_AGENT_SYSTEM_DESIGN.md` | 部分可观测比赛中的在线闭环设计 |
| `OWNED_ENTERPRISE_AGENT_SYSTEM.md` | 仅控制我方企业的滚动决策系统 |
| `COLLABORATIVE_AGENT_DESIGN.md` | 我方一家企业内部六专业 Agent 的协同协议、指标定义和校准结果 |
| `CLICKABLE_COMPETITION_PLATFORM.md` | 可点击的人机/多人比赛平台、启动方式、接口与部署边界 |
| `XA_REPLAY_FIDELITY.md` | 历史结果回放与因果模拟的边界 |
| `XA_INTERMEDIATE_RECONSTRUCTION.md` | XA 中途状态反推和规则校准 |
| `XA_HISTORICAL_STRATEGY_REPLAY.md` | 27 家历史策略重建和三种模拟模式 |
| `XA_REAL_VS_SIMULATION_ANALYSIS.md` | 真实 XA 与模拟比赛结果差异 |

优先阅读顺序为：项目路线图 → 系统架构 → 在线 Agent 设计 → XA 历史重建与模拟边界。
