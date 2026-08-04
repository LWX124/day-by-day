# Backend Development Guidelines

> daybyday-agent（Python 后端）开发规范。后端是 SwiftUI 外壳的子进程，负责所有决策与数据。

---

## Overview

后端分层核心：**`core/` 纯函数域禁依赖外部**（LLM/网络/IO），所有判定住在这里可单测可离线。详见各文件。

分层依据见 `.trellis/docs/design.md` §1、ADR-0001（双进程）、ADR-0003（推断/判定分离）。

---

## Pre-Development Checklist

写后端代码前确认：

- [ ] 这段逻辑是**判定**还是 **IO**？判定必须进 `core/` 且不读系统时钟（now 作参数）。
- [ ] 写状态走 `events.append` 了吗？没有直接 UPDATE 投影表。
- [ ] `core/` 新文件没有 import agent/store/api/collectors/scheduler/langchain（CI 会拦）。
- [ ] 外部调用（LLM/git/Gerrit）包了 try 并转成 `ProviderUnavailable`/`CollectorError`？
- [ ] 对外写操作（Gerrit/删任务）走了确认流？

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | 分层目录与 core 纯函数红线 | ✅ 已填 |
| [Database Guidelines](./database-guidelines.md) | SQLite 事件流 + 投影 + 迁移 | ✅ 已填 |
| [Error Handling](./error-handling.md) | 三类错误与降级策略 | ✅ 已填 |
| [Quality Guidelines](./quality-guidelines.md) | forbidden patterns、import-linter、测试要求 | ✅ 已填 |
| [Logging Guidelines](./logging-guidelines.md) | 结构化日志、分级、脱敏 | ✅ 已填 |

---

## Quality Check

提交前自查：

- [ ] `uv run ruff check` 通过
- [ ] `uv run mypy` 通过
- [ ] `uv run lint-imports` 通过（core 纯函数约束）
- [ ] `uv run pytest` 通过，core 覆盖率达标
- [ ] 新事件 kind 已加入重放逻辑

---

**语言**：本工程文档用**中文**。
