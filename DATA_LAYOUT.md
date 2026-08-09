# GoAI 数据布局

本仓库保存代码、测试、文档，以及体积适合 GitHub 的规范化数据、模拟数据和 Agent-ready 索引。原始比赛文件、模型缓存和未来大规模实验结果位于仓库外，避免重复复制；所有模拟数据都必须明确标记 provenance，不能作为历史事实。

## 当前开发机布局

```text
/home/undefined/Desktop/GoAI/
├── origin data -> /home/undefined/Desktop/Others/goai/origin data
├── data/                         # 已同步到 Git 的规范化和模拟数据
└── docs/PROJECT_STATUS_AND_AGENT_PLAN.md

/home/undefined/Disk/datasets/goai/        # 当前开发机的原始共享副本
├── processed/v1/                 # 通用标准化 CSV、SQLite、数据字典和质量报告
├── processed/v2/matches/         # 14 场比赛的结构化数据、规则和回放产物
└── simulations/                  # 明确标记为 simulated 的沙盘批次
```

`origin data` 被 `.gitignore` 排除，是本机兼容链接，不能假设在其他机器上存在。仓库内 `data/` 是已同步的小于 GitHub 单文件限制的数据副本；如需节省克隆空间，可以删除它并改用外部共享目录。

## 在新机器上使用

1. 克隆本仓库。
2. 将原始资料复制或软链接为仓库根目录的 `origin data/`。
3. 将共享数据目录复制或软链接为仓库根目录的 `data/`，或在脚本参数中显式传入数据路径。
4. 使用共享 Python 环境 `/home/undefined/Disk/python-envs/goai-py312/bin/python`，或创建等价的 Python 3.12 环境并安装 `pyproject.toml` 依赖。

当前仓库已经提交 `data/processed/`、`data/simulations/` 和 `data/agent_ready/` 中体积受控、可公开复现的数据。新增大型批次、模型文件、缓存、原始资料和浏览器临时导出不得直接提交；应先检查单文件和仓库总体积，并保留 `provenance` 字段，避免模拟产物被误用为正式历史事实。
