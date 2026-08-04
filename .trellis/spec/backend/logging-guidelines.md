# Logging Guidelines

> Swift 与 Python 写同一份日志目录，单一时间线便于跨进程排查。

---

## Overview

- **库**：Python 标准库 `logging`，结构化输出（key=value 或 JSON）。
- **目录**：`~/Library/Application Support/DayByDay/logs/`，与 Swift 侧一致。BackendSupervisor 把 Python stdout/stderr 重定向到这里。
- **轮转**：`RotatingFileHandler`，单文件 5MB，保留 5 份。
- **时区**：所有时间戳 ISO8601 带时区，与 `events.occurred_at` 一致。

---

## Log Levels

| 级别 | 用途 |
|---|---|
| `DEBUG` | 本地开发：函数入参、LLM prompt/响应（注意脱敏 key） |
| `INFO` | 正常业务事件：任务创建、nag 发送、复盘触发、迁移执行、后端启动/重启 |
| `WARNING` | 降级发生（LLM 不可用切降级、Gerrit 超时跳过）、待确认动作超时作废、补偿触发补齐漏掉的 occurrence |
| `ERROR` | InvariantError、scheduler job 失败、后端崩溃前的最后状态、git 白名单越权尝试被拒 |

生产（即你日常自用）默认 INFO，本地 DEBUG 用环境变量 `DBD_LOG_LEVEL=DEBUG`。

---

## Structured Logging

每条日志带固定字段：

```
2026-08-04T18:30:01+08:00 INFO actor=scheduler event=daily_review_triggered review_date=2026-08-04
```

- `actor`：user | agent | scanner | scheduler | system（与 `events.actor` 对齐）。
- 业务相关日志带 `task_id` / `review_date` / `kind` 等上下文字段，便于 grep。
- LLM 调用日志带 `provider`、`model`、`latency_ms`、`token_usage`，**不**带完整 prompt（DEBUG 级才带，且脱敏 key）。

---

## What to Log

- 所有状态转移（任务创建/完成/改期/abandon）。
- 所有 nag 发送与 Re-decision 触发。
- Daily Review 触发、降级、missed。
- 后端启动、崩溃重启、退避计数。
- git/Gerrit 采集成功与失败。
- 待确认动作的登记、确认、作废。
- git 白名单越权尝试（ERROR，这是安全信号）。

---

## What NOT to Log

- **LLM API key / Provider token**——永不记录。DEBUG 级的 prompt 也要确认不含 key。
- **diff 正文**——evidence 只记元数据（commit 数/行数/分支），diff 正文不进日志（虽 ADR-0004 数据边界不设限，但日志是另一回事，避免日志泄露）。
- **用户复盘原话全文**——只记 review_id 与 summary，原话在库里按需查。
