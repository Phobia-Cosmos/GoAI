# GoAI 数据布局

本仓库只保存代码、测试、示例和轻量文档。原始比赛资料、处理后数据、模型缓存和大规模模拟结果位于仓库外，避免重复复制和把模拟/私有资料纳入 Git。

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

不要把 `processed/`、`simulations/`、模型文件、缓存或浏览器导出的临时文件提交到 Git。原始资料和模拟产物都应保留其 `provenance` 字段，避免被误用为正式历史事实。
