# Swift 外壳 + Python agent 后端双进程

宠物层的硬需求（透明无边框窗口、始终置顶、跨 Space、隐藏 Dock 图标、点击穿透的全屏特效层、系统通知、开机自启）在 macOS 上只有原生 AppKit/SwiftUI 能低成本满足；而 agent 层（LangGraph、多 provider、git/Gerrit 扫描、调度）迭代频率远高于 UI 且生态在 Python。因此拆成两个进程：SwiftUI 负责渲染与用户事件，Python 负责一切决策与数据，两者通过 loopback HTTP（Swift → Python）+ SSE（Python → Swift 推命令）通信。

## Consequences

- Swift app 作为父进程 spawn 并守护 Python 后端（退避重启、stdout 汇入统一日志、app 退出即回收），**不**用 launchd 独立常驻后端：UI 挂了后端活着也没有呈现渠道，独立常驻只换来两处日志、版本漂移和开发期跑起两份后端的风险。
- 前后端版本永远一致，因为它们同生同死。
- 分发时 Python 运行时需随 app 打包（自用阶段可先依赖本机 uv 环境）。
