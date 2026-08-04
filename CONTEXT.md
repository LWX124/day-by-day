# Day by Day

一个常驻 macOS 桌面的电子宠物，替你管日程与工作任务：主动提醒、每日复盘、按周期出报告，并用情绪反馈（庆祝与鞭策）维持你的执行力。

本文件只定义术语，不含任何实现细节。设计见 `.trellis/docs/design.md`。

## 语言

### 任务

**Task（任务）**：
一件你打算做的事，是系统里唯一的工作单元。
_Avoid_: Todo、事项、Item

**Schedule（时间语义）**：
Task 的时间性质，四取一：OneShot、Deadline、Recurring、Openended。它决定这个 Task 会不会被催、以及怎么被催。
_Avoid_: 类型、Type、Kind

**OneShot（一次性）**：
做完就结束、没有约定期限的 Task。例：修好这个 bug。

**Deadline（有截止）**：
约定了完成时点的 Task。例：1 个月内完成 X。
_Avoid_: 有期限任务、DDL 任务

**Recurring（周期）**：
按规则反复发生、不存在"超期"概念的 Task，只有做与没做。例：每天读 5 页书。
_Avoid_: 习惯、打卡任务、Habit

**Openended（无期限）**：
长期挂着、没有完成时点也无固定节奏的 Task。例：学 Rust。
_Avoid_: 长期任务、挂起任务

**Occurrence（当日实例）**：
Recurring Task 在某一天上的具体实例，是打卡的对象。
_Avoid_: 实例、打卡项、Instance

**Check-in（打卡）**：
对某个 Occurrence 记录进展，可以是完成也可以是部分完成。
_Avoid_: 签到、完成打卡

**Weight（重量）**：
Task 的体量等级（S/M/L/XL），决定它值多大的庆祝，也影响多久没动静才该被催。
_Avoid_: 优先级、Priority、大小、难度

### 历史

**Task Event（任务事件）**：
一次不可变的、已发生的变更记录（建立、状态转移、改期、打卡、复盘回答等）。事件流是系统的唯一事实来源。
_Avoid_: 日志、Log、变更记录

**Projection（投影）**：
由 Task Event 重放得出的当前状态视图。投影可以随时丢弃重建。
_Avoid_: 快照、缓存、视图

**Activity Evidence（活动证据）**：
从外部系统（本地 git 仓库、Gerrit）采集到的、暗示某个 Task 有进展的客观事实。它永远只是证据，不构成状态。
_Avoid_: 进度、完成度、状态推断

### 主动性

**Nag（催办）**：
系统就某个久未推进的 Task 主动发起的追问，语气随次数递增。
_Avoid_: 提醒、Reminder、通知

**Re-decision（重新决策）**：
Nag 的终点。当追问累计到上限仍无响应，系统不再催"快做"，而是要求你在改期、降级、放弃之间做出选择。
_Avoid_: 放弃、清理、归档

**Daily Review（每日复盘）**：
每天傍晚由宠物发起的一轮对话，逐项确认当天任务状态并把结论写回事件流。
_Avoid_: 日报、总结、Standup

**Period Report（周期报告）**：
对一段时间的事件流做聚合后生成的成文报告，周报与月报是它的两种周期。
_Avoid_: 周报（单指周期为一周的 Period Report）、汇总

### 宠物

**Pet（宠物）**：
桌面上那个常驻的可视化形象，是系统与你之间唯一的交互入口。
_Avoid_: 助手、Agent、挂件

**Emotion State（情绪状态）**：
Pet 当前的表现状态（如平静、开心、担忧、不满、睡眠），由任务积压情况推导，不由 LLM 决定。
_Avoid_: 心情、表情、动画状态

**Celebration（庆祝特效）**：
Task 完成时播放的视听反馈，按 Tier 分四档，从粒子微闪到满屏烟花。
_Avoid_: 特效、动画、奖励

**Tier（特效档位）**：
Celebration 的强度等级（1–4），由 Weight、拖延时长和里程碑共同算出。
_Avoid_: 等级、Level

### 外部关联

**Project（项目）**：
一个被记住的代码产物，带名称、口语别名、本地路径和 Gerrit 仓库名。Task 关联 Project，而不是关联裸路径。
_Avoid_: 仓库、Repo、目录

**Note（笔记）**：
一条自由文本知识，可挂在某个 Project 或若干标签下，供 LLM 读取。
_Avoid_: 记忆、Memory、知识条目

**Provider（模型供应方）**：
一个可配置的 LLM 服务端点（如百炼、DeepSeek、微博内部网关）。
_Avoid_: 模型、Model、LLM
