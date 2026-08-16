# 腾讯云演示部署

本目录只保存StratPilot Web Demo 的云托管容器定义。实际部署上下文由脚本临时整理，仅包含 `src/goai_data`、Web 启动脚本和一份模拟规则模板；不会上传 `data/original`、历史比赛数据、实验输出、项目文档或 Git 仓库元数据。

当前服务名为 `stratpilot-demo`，容器监听 CloudBase 提供的 `PORT`。这是比赛展示用的内存会话服务，不是生产环境：实例重启后比赛会话失效，也不提供正式账号系统。

当前公开兼容演示入口为 `https://arithmetic-challenge-d0ac567f37e.service.tcloudbase.com/stratpilot`，HTTP 路由指向 `stratpilot-competition`。旧 `/qice` 路由暂时保留并指向旧函数，仅用于兼容早期材料；公开文档和 GitHub homepage 应使用 `/stratpilot`。
