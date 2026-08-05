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


## Session 8: Provider 抽象与配置（provider-abstraction）

**Date**: 2026-08-04
**Task**: Provider 抽象与配置（provider-abstraction）
**Branch**: `main`

### Summary

LLM Provider抽象+fallback链+降级标记，170测试，check修了errors基类缺字段

### Main Changes

- agent/providers.py：ProviderFactory(openai_compatible→ChatOpenAI)+LLMRouter(default+fallback链)+is_available降级标记
- common/config.py：LLMConfig.available 收紧为 env 实际有值
- common/errors.py：DayByDayError 基类加 message/detail 字段（check修复预存my流问题）
- tests/agent/test_providers.py(15)+tests/common/test_errors.py(3)

### Git Commits

(No commits - planning session)

### Testing

- [OK] ruff/mypy agent+common strict/lint-imports KEPT/pytest 170 全绿
- [OK] 探针：default成功不走fallback/default失败走fallback/全失败抛ProviderUnavailable/无key返回None/链顺序正确/缺key跳过

### Status

[OK] **Completed**

### Next Steps

- 真实chat验收待DASHSCOPE/DEEPSEEK key；start langgraph-skeleton


## Session 9: LangGraph 图骨架（langgraph-skeleton）

**Date**: 2026-08-04
**Task**: LangGraph 图骨架（langgraph-skeleton）
**Branch**: `main`

### Summary

主图classify→3节点分发+SqliteSaver checkpointer+降级路由，181测试，踩清SqliteSaver连接坑

### Main Changes

- agent/graph.py：build_graph，START→classify→{ingest_task|query_status|freeform}→END，SqliteSaver同库独立表
- agent/nodes/{classify,ingest_task,query_status,freeform}.py：意图分类+建任务落库+查状态+通用对话，全降级走规则
- agent/graph._open_conn：isolation_level=None+check_same_thread=False+WAL+busy_timeout（SqliteSaver连接坑）
- store/db.py：删除死代码 get_sqlite_saver_conn（默认值对SqliteSaver跨线程是错的）
- spec/backend/database-guidelines：固化 SqliteSaver 连接坑
- pyproject.toml：加 langgraph-checkpoint-sqlite

### Git Commits

(No commits - planning session)

### Testing

- [OK] ruff/mypy agent 8files/lint-imports KEPT/pytest 181全绿，连跑3次无flake
- [OK] 7项端到端探针：路由/落库deadline/checkpointer持久化/断点续跑/线程隔离/连续invoke不崩

### Status

[OK] **Completed**

### Next Steps

- start structured-extraction：LLM结构化抽取+置信度


## Session 10: 结构化抽取与置信度（structured-extraction）

**Date**: 2026-08-04
**Task**: 结构化抽取与置信度（structured-extraction）
**Branch**: `main`

### Summary

TaskDraft+置信度物化落库+反问，211测试，check修了正则误判/改due有效性/投影缺schedule_kind

### Main Changes

- agent/extraction.py：TaskDraft(schedule/due/weight/project+confidence_per_field)+extract()(LLM with_structured_output/规则双路径)+draft_to_task_created_payload物化tasks.inference
- agent/nodes/ingest_task.py：三种语义分流(建任务高置信落库低置信反问/做完了标完成/改due落事件)
- agent/nodes/classify.py：_INGEST_DONE_RE 加负向前瞻(check修复做完了吗误判)
- store/projections.py：_apply_fields_updated 加 schedule_kind 列(check修复kind切换被丢)
- tests/agent/test_extraction.py(17)+test_ingest.py(11)

### Git Commits

(No commits - planning session)

### Testing

- [OK] ruff/mypy agent+store 13files/lint-imports KEPT/pytest 211全绿
- [OK] 8项探针：deadline/recurring/做完了/openended反问/改due/非法组合UserError/置信度阈值/inference物化

### Status

[OK] **Completed**

### Next Steps

- start tool-registry：Tool注册表+授权分级


## Session 11: 修复 GUI 启动 127 + PetPanel 不上屏

**Date**: 2026-08-05
**Task**: 修复 GUI 启动 127 + PetPanel 不上屏
**Branch**: `main`

### Summary

GUI app 经 launchd 启动 PATH 不含 ~/.local/bin，/usr/bin/env uv 找不到 → code=127。修 BackendSupervisor 探测 uv 绝对路径 + 注入子进程 PATH + 确定性失败快速失败 + uvicorn stdout 端口解析 + 真实 /health 探活 + 单一重启路径（修双重计数/孤儿进程）。过程中暴露第二个 bug：borderless NSPanel 因 hidesOnDeactivate 默认 true 不上屏（isVisible=true 但屏幕无渲染），诊断特征是朴素 NSWindow 可见、PetPanel 不可见，修法是显式关掉 hidesOnDeactivate/becomesKeyOnlyIfNeeded + .nonactivatingPanel。真机验证 LSUIElement=YES 下后端 /health 200、宠物窗口正常显示。新增 run.sh 不开 Xcode 即可编译启动。沉淀 process-supervision.md 与 quality-guidelines §6 panel 坑。

### Git Commits

| Hash | Message |
|------|---------|
| `978dacd` | (see git log) |
| `71a4f2d` | (see git log) |
| `92ff8cd` | (see git log) |
| `c58c66d` | (see git log) |
| `da998c7` | (see git log) |

### Status

[OK] **Completed**


## Session 12: 修复后端启动日志崩溃与 token 噪音

**Date**: 2026-08-05
**Task**: 修复后端启动日志崩溃与 token 噪音
**Branch**: `main`

### Summary

修复 api/__main__.py:59 %d 格式崩溃（port=0 时配字符串）和 api/app.py _dev_token() warning 降级为 info，消除 __main__.py 路径下的 token 噪音。验证：python -m api --token 启动无异常，日志正常。

### Git Commits

| Hash | Message |
|------|---------|
| `69b082f` | (see git log) |

### Status

[OK] **Completed**


## Session 13: Tool 注册表与授权分级提交

**Date**: 2026-08-05
**Task**: Tool 注册表与授权分级提交
**Branch**: `main`

### Summary

提交已完成的 tool-registry 代码（8月4日编写，28个测试全过）。实现 ADR-0004 三级授权：read/write/confirm。读级 Tool 自由调用，常规写 Tool 直接落库+event_id+可撤销，confirm 级 Tool 只生成 pending_action+push RequestConfirm 不落地。包含 registry.py/read.py/write.py/confirm.py 和完整测试覆盖。

### Git Commits

| Hash | Message |
|------|---------|
| `6039c78` | (see git log) |

### Status

[OK] **Completed**
