# Day by Day — 实施计划

设计见 [`design.md`](./design.md)，术语见 [`CONTEXT.md`](../../CONTEXT.md)。

排期原则：**先"能用"再"好看"**——没有任务数据时，特效无处可放、扫描无人消费。sprite 素材生产周期长，从第一天并行启动。

---

## 里程碑总览

| 期 | 目标 | 完成后你能做什么 |
|---|---|---|
| M0 | 骨架 | 宠物在桌面上，单击能看到手工建的今日任务 |
| M1 | 自然语言录入与查询 | 对宠物说一句话就建好任务，问它"今天干什么" |
| M2 | 主动性 | 它会在 18:30 找你复盘、会催久未推进的任务 |
| M3 | 情绪反馈 | 完成任务有分级特效，满屏烟花 |
| M4 | 外部证据 | 关联目录/Gerrit，问状态时它给你看客观证据 |
| M5 | 报告 | 一句话出周报/月报 |
| M6 | Gerrit 写操作 | 面板里直接打分/abandon/rebase |

---

## M0 骨架

**Python 侧**
- 项目脚手架：uv + FastAPI + pytest；`core/` `store/` `api/` 分层，`core/` 禁止 import LLM（用 import-linter 或一条 CI 检查钉死）
- `store/`：迁移框架 + `events` 与全部投影表建表 + 事件 append/重放/撤销 + 从 events 重建投影的函数
- `core/`：`Schedule` 四态联合类型与非法组合校验、`ensure_occurrences_up_to`（含 backfill）、`today_view`
- `api/`：`/today` `/tasks`（手工 CRUD）`/events`(SSE) + token 鉴权，只 bind 127.0.0.1

**Swift 侧**
- Xcode 项目，`LSUIElement = true`
- `PetWindow`（透明无边框 / floating / canJoinAllSpaces）+ 拖拽挪位 + 位置持久化
- `PetRenderer` 协议 + **开发期占位实现**（SF Symbols + SwiftUI 动画）
- `BackendSupervisor`：spawn Python、传端口与 token、退避重启、stdout 汇入 `logs/`
- `TaskCardWindow`（单击）、右键菜单、SSE 客户端接 PetCommand

**验收**
- 手工建 4 种 schedule 的任务各一条，单击宠物能看到今日该做什么，Recurring 出现当日实例
- 杀掉 Python 进程，宠物 8 秒内自动恢复连接
- 把机器睡到第二天再唤醒，漏掉的 Occurrence 被补齐且不重复
- 删掉全部投影表后能从 events 完整重建

**风险**：透明窗口 + 跨 Space + 不抢焦点的组合是这一期唯一有未知的地方，先写一个 30 行的 spike 验证再铺代码。

---

## M1 自然语言录入与查询

- `agent/`：Provider 抽象与 `config.toml` 解析、`ChatOpenAI(base_url)` 适配、失败 fallback 链
- LangGraph 图 + `SqliteSaver`，先接 `classify` / `ingest_task` / `query_status` / `freeform` 四个节点
- 结构化抽取：pydantic 模型输出 Schedule + due + Weight + Project 引用 + **每字段置信度**；高置信直接落库并回执，低置信反问一句
- Tool 注册表与授权分级框架（读 / 常规写 / 需确认三级），`pending_action` 与 `/confirm` 通路
- `POST /intent`；面板里的对话框（PanelWindow 先只做「对话」和「今日」两个分区）
- **无 key 降级模式**：agent 不可用时 UI 隐藏对话入口，其余功能不受影响

**验收**
- 说"下周三前把登录重构做完"→ 建出 `deadline` 任务、due 正确、Weight 有值、回执一行
- 说"每天读 5 页书"→ 建出 `recurring` 任务，当日实例出现在今日视图
- 说"那个重构做完了"→ 正确匹配任务并标完成，且能一句话撤销
- 清空 API key 后，提醒/统计/打卡全部照常工作

---

## M2 主动性

- `core/nag.py`：四个 schedule 策略对象 + `idle_threshold(weight)` / `lead_days(weight)` 配置化
- Nag 升级链（轻推→认真问→鞭策）与 **Re-decision 终点**（3 次后转改期/降级/放弃，决策后计数清零）
- `scheduler/`：APScheduler 装配 `hourly_tick` / `daily_review` / `weekly_prompt`
- Swift 侧监听 `NSWorkspace.didWakeNotification` → `POST /wake`
- Daily Review 触发协议全套：18:30 非侵入提示 → 30 分钟降级为徽标 → 睡眠错过在 23:00 前补触发 → 超窗标 missed 并入次日早报；周末跳过开关
- `daily_review` 节点：候选清单（今日应做 / 有活动未标完成 / 断签）逐项问，结论写回事件流
- 系统通知权限申请与 `notify` PetCommand

**验收（这一期的验收必须靠伪造时钟，不能靠等）**
- `core/nag.py` 的单测覆盖四种 schedule × 各自边界：`deadline` 未到提醒窗口一声不出；`recurring` 无论挂多久都不因总时长触发；`one_shot` 按 Weight 阈值触发；`openended` 月度触发
- 同一任务连续 3 次 Nag 无响应后，第 4 次收到的是 Re-decision 而非催促
- 18:30 复盘中断在半句，21:00 回复能接上上文（同一 `thread_id`）

---

## M3 情绪反馈

- `core/celebration.py`：Tier 函数（Weight 基线 + 拖延加成 + 里程碑加成，clamp 4）
- `core/emotion.py`：Emotion State 推导（纯函数，不经 LLM）
- `CelebrationOverlayWindow`：全屏 / `.screenSaver` level / `ignoresMouseEvents` / 跨 Space；SpriteKit 粒子烟花，Tier 3 约 3s、Tier 4 约 8s + 大字文案 + 音效
- Tier 1–2 在宠物窗口内完成（点头/欢呼/彩带）
- **sprite sheet 正式接入**：`SpriteSheetPetRenderer` 替换占位实现，状态机对接 Emotion State
- 鞭策文案由 LLM 生成（语气按 nag_count 递增），降级模式下用模板

**验收**
- 四档特效各自触发一次，Tier 3–4 期间可以正常在下面的编辑器里打字（点击穿透生效）
- 拖了一个月的 M 任务完成时拿到 Tier 4，不是 Tier 2
- 全屏烟花播放期间 CPU 峰值可接受，播完 overlay 窗口销毁不残留

---

## M4 外部证据

- `collectors/git.py`：只读子命令白名单、参数数组 exec 不经 shell、拒绝 `-c` 类注入、工作目录必须落在某 Project 的 `local_path` 内
- `collectors/gerrit.py`：SSH CLI 查询（`gerrit query --format=JSON --current-patch-set`），适配 **2.8.4** 的输出格式
- `projects` / `notes` 的 CRUD 与**别名解析**（说"主站"能命中）
- Task 关联 Project（可空）；`EvidenceCollected` 事件与 `activity_evidence` 落库
- 复盘候选里接入 Evidence：把"有活动但未标完成"挑出来问；Gerrit merged 的权重高于本地 commit
- "待我评审"堆积超阈值时触发 Nag
- PanelWindow 增加「Gerrit」「知识」两个分区（只读）

**验收**
- 问"登录重构那个咋样了"→ 返回 commit 数/时间跨度/分支/Gerrit change 状态，且**明确不改任务状态**
- git 白名单越权测试：尝试让 agent 执行 `git reset --hard` 被拒绝且记日志
- 改一个 Project 的 `local_path`，所有关联任务立即生效（无需逐个改）

---

## M5 报告

- `core/stats.py`：按时间段聚合事件流（完成数/按 Weight 分布/逾期次数/改期次数/断签率/Recurring 完成率）
- `period_report` 节点：`core` 给数字，LLM 组织成文并**引用你在 Daily Review 里说过的原话**
- `reports` 表落库；PanelWindow「复盘历史」分区可回看与导出 Markdown
- 周日 20:00 气泡提示可生成周报（不自动生成）

**验收**
- 周报里的每个数字都能在事件流里对上；同一时间段重复生成，数字完全一致
- 中间有 2 天没做 Daily Review，周报仍能基于事件流写出内容（不出现黑洞）

---

## M6 Gerrit 写操作

- `gerrit_review_vote` / `gerrit_abandon` / `gerrit_rebase` 三个 tool，**全部走 `request_confirm`**
- 确认框展示 change 主题、owner、改动行数，并提供"在浏览器打开"按钮——不鼓励盲打分
- LLM 不得自主发起写操作；只能在你明确指令或面板点击后进入确认流

**验收**：agent 在自由对话里被诱导执行 +2 时，只会生成待确认动作，绝不直接落地。

---

## 并行工作流：sprite 素材

从 M0 第一天启动，M3 前必须就位。

- 状态清单：`idle` / `happy` / `focused` / `worried` / `grumpy` / `sleeping`，每状态 8–12 帧
- 动作清单：`nod`（Tier 1）/ `cheer`（Tier 2）/ `special`（Tier 4）
- 产出规范：@2x sprite sheet PNG + JSON 帧描述（帧尺寸、帧数、fps、循环点），放 `assets/`
- 风格先定一版参考图并锁死，再批量生成，避免风格漂移后全部重做

---

## 横向事项

- **`.trellis/spec` 填充**：M0 收尾时把 `backend/`（Python 分层、`core` 纯函数约束、事件流写入规范）和 `frontend/`（Swift 窗口层级、PetCommand 处理、渲染层协议）的空模板填上真实约定，否则后续 sub-agent 会写出跑偏的代码
- **测试策略**：`core/` 要求高覆盖且不 mock LLM；`store/` 覆盖重放与撤销；agent 层只做少量端到端冒烟
- **日志**：Swift 与 Python 统一写 `~/Library/Application Support/DayByDay/logs/`，单一时间线便于排查
- **待确认外部信息**：微博内部 LLM 网关的 base_url 与协议（是否 OpenAI-compatible）。不阻塞任何一期——M1 先用百炼/DeepSeek 打通，网关信息到手后加一个 provider 配置块即可，协议不兼容才需要写 `BaseChatModel` 子类
