# Journal - lwx (Part 1)

> AI development session journal
> Started: 2026-08-04

---



## Session 1: 填充 .trellis/spec（spec-bootstrap）

**Date**: 2026-08-04
**Task**: 填充 .trellis/spec（spec-bootstrap）
**Branch**: `main`

### Summary

填充 backend 与 frontend 全部 spec 模板，钉死 core 纯函数红线

### Main Changes

- backend: directory-structure（分层 + core 禁依赖红线 + import-linter 规则）
- backend: database-guidelines（SQLite 事件流 + 投影 + 迁移，禁直接改投影表）
- backend: error-handling（三类错误 + 降级保活）
- backend: logging-guidelines（结构化日志 + 脱敏 + 与 Swift 同目录）
- backend: quality-guidelines（forbidden patterns 含 core 红线 + 测试要求）
- frontend: directory-structure（窗口/渲染/视图分层）
- frontend: component/hook/state/quality/type 全部从 React 模板重映射到 Swift macOS
- backend/frontend index 加 Pre-Development Checklist + 勾选状态

### Git Commits

(No commits - planning session)

### Testing

- [OK] grep 检查无 To be filled 残留

### Status

[OK] **Completed**

### Next Steps

- start py-scaffold 搭 Python 骨架


## Session 2: Python 脚手架与分层约束（py-scaffold）

**Date**: 2026-08-04
**Task**: Python 脚手架与分层约束（py-scaffold）
**Branch**: `main`

### Summary

搭建 daybyday-agent 骨架，钉死 core 纯函数红线，实现 schedule/celebration 两个纯函数

### Main Changes

- pyproject.toml：uv 项目 + 依赖 + ruff/mypy/import-linter 配置
- 分层目录 core/store/agent/collectors/scheduler/api/common + 各包 __init__ 职责说明
- core/schedule.py：Schedule 四态联合类型 + 非法组合校验（含跨 kind 独有字段）+ idle_threshold/lead_days
- core/celebration.py：celebration_tier 纯函数（Weight 基线 + 拖延加成 + 里程碑 + clamp）
- common/config.py：config.toml 加载 + 数据目录路径 + 降级标记
- api/app.py：占位 FastAPI + /health + Bearer token 鉴权
- tests/core：16 个测试（schedule 11 + celebration 5）

### Git Commits

(No commits - planning session)

### Testing

- [OK] ruff/pytest 16/mypy --strict/lint-imports 全绿
- [OK] core 红线实测：langchain_core/langchain_openai/langgraph/agent 越界 import 均被拦
- [OK] uvicorn 启动 + /health + token 鉴权（200/401）
- [OK] config.toml 解析（正常 + 缺失降级）

### Status

[OK] **Completed**

### Next Steps

- start event-store：SQLite 建表 + 事件流 append/重放/撤销/投影重建


## Session 3: 事件流存储与投影（event-store）

**Date**: 2026-08-04
**Task**: 事件流存储与投影（event-store）
**Branch**: `main`

### Summary

实现 SQLite 事件流地基：8 张表 + append/重放/撤销 + 投影重建，46 测试全绿

### Main Changes

- store/migrations/0001_init.sql：8 张表（events/tasks/occurrences/projects/notes/activity_evidence/daily_reviews/reports）+ 2 索引，严格按 design §4
- store/db.py：WAL+外键+busy_timeout、run_migrations（编号顺序/幂等/失败回滚该文件）、init_db、get_sqlite_saver_conn 占位
- store/events.py：12 事件 kind 枚举、append（kind 校验+payload JSON）、undo（EventUndone+反向指针不物理删）、replay（按时间序跳过被 undone）
- store/projections.py：rebuild_tasks/occurrences/all（先清空再重放，唯一投影写入路径）
- tests/store：30 测试覆盖 4 验收标准（4 种 schedule+打卡+改期、删表重建、撤销回退、迁移幂等）

### Git Commits

(No commits - planning session)

### Testing

- [OK] ruff/mypy store strict/pytest 46/lint-imports KEPT 全绿
- [OK] 边界：二次撤销/撤销不存在/同时间戳稳定序/嵌套JSON往返/迁移失败回滚/并发append

### Status

[OK] **Completed**

### Next Steps

- start core-domain：ensure_occurrences_up_to + today_view + 状态机


## Session 4: core 纯函数域（core-domain）

**Date**: 2026-08-04
**Task**: core 纯函数域（core-domain）
**Branch**: `main`

### Summary

实现 ensure_occurrences/today_view/nag 四策略，57 新增测试，需求10三例外验准

### Main Changes

- core/occurrence.py：ensure_occurrences_up_to 纯函数内核（DAILY/WEEKLY+INTERVAL+BYDAY、幂等、过去冻结、不碰DB）
- core/views.py：today_view（deadline 未到 lead_days 不进催办区、recurring 当日、in_progress 三区）
- core/nag.py：四策略对象+due_nags（one_shot idle/deadline lead_days窗口/recurring断签≥2/openended月度）
- tests/core：occurrence 13+views 16+nag 28=57 新增

### Git Commits

(No commits - planning session)

### Testing

- [OK] ruff/mypy strict 11 files/lint-imports KEPT/pytest 103 全绿
- [OK] 需求10三例外逐条验准：deadline未到期不催、recurring不因总时长催、长任务区分（15临时探针验证后删）

### Status

[OK] **Completed**

### Next Steps

- start api-sse：FastAPI 端点+SSE PetCommand+token鉴权


## Session 5: API+SSE 通信层（api-sse）

**Date**: 2026-08-04
**Task**: API+SSE 通信层（api-sse）
**Branch**: `main`

### Summary

PetCommand 7种+SSE+token鉴权+全端点，149测试，check修了token契约违背和FK崩溃bug

### Main Changes

- api/commands.py：7种PetCommand discriminated union+PetCommandBus fan-out
- api/models.py：请求/响应DTO
- api/routes.py：/today /tasks(手工CRUD) /intent /confirm /wake(占位) /events(SSE)
- common/errors.py：DayByDayError体系+统一{error,message,detail}响应
- api/__main__.py：命令行入口（check修复，对应PRD token不进环境变量）

### Git Commits

(No commits - planning session)

### Testing

- [OK] ruff/mypy api 6files/lint-imports KEPT/pytest 149 全绿
- [OK] check修复：token改create_app(token)注入+secrets.compare_digest防侧信道
- [OK] check修复：rebuild_all FK崩溃bug（先清子表再清父表）+回归测试
- [OK] check补：端口释放永久测试test_port_released_after_server_exit

### Status

[OK] **Completed**

### Next Steps

- start swift-window-spike：Swift原生窗口+宠物显示


## Session 6: Swift 窗口 spike（swift-window-spike）

**Date**: 2026-08-04
**Task**: Swift 窗口 spike（swift-window-spike）
**Branch**: `main`

### Summary

SwiftUI app+PetPanel+CelebrationOverlay，编译通过，学清NSPanel只读属性只能子类重写

### Main Changes

- project.yml：xcodegen 配置，LSUIElement=true 隐藏 Dock
- DayByDayApp.swift：NSApplicationDelegateAdaptor 驱动，spike 验收菜单
- Windows/PetWindow.swift：PetPanel 子类（透明/置顶/跨Space/不抢焦点/可拖拽）
- Windows/CelebrationOverlay.swift：全屏 NSPanel screenSaver level+ignoresMouseEvents 点击穿透
- Rendering/PetView.swift：SF Symbols+SwiftUI 动画占位
- spec/frontend/quality-guidelines §6 §7：固化 NSPanel 只读属性子类重写坑 + GUI验收脚本

### Git Commits

(No commits - planning session)

### Testing

- [OK] xcodebuild BUILD SUCCEEDED
- [OK] LSUIElement=1 确认
- [OK] app 进程启动

### Status

[OK] **Completed**

### Next Steps

- 肉眼验收跨Space/overlay点击穿透/拖拽（需本机GUI权限）


## Session 7: BackendSupervisor 守护（backend-supervisor）

**Date**: 2026-08-04
**Task**: BackendSupervisor 守护（backend-supervisor）
**Branch**: `main`

### Summary

Swift spawn/守护Python后端，退避重启+日志汇流+位置持久化+健康联动情绪

### Main Changes

- App/BackendSupervisor.swift：spawn uv run python -m api --token/--host/--port，退避1s→2s→4s→8s→30s，连续5次failed，SIGTERM+SIGKILL回收，日志汇入agent.log，32字节随机token命令行传入
- Utilities/PositionStore.swift：UserDefaults 持久化宠物拖拽位置
- Utilities/WakeMonitor.swift：NSWorkspace.didWakeNotification 监听（M2接POST /wake）
- Windows/PetWindow.swift：接入 supervisor+位置恢复+健康联动情绪(健康idle/降级worried/失败grumpy)

### Git Commits

(No commits - planning session)

### Testing

- [OK] xcodebuild BUILD SUCCEEDED

### Status

[OK] **Completed**

### Next Steps

- 肉眼验收：kill Python 8秒恢复/连续5次worried/退出无残留/位置保持
