# Quality Guidelines

> 后端代码质量标准。**第一条 forbidden pattern 是全工程最重要的架构红线。**

---

## Overview

- **lint**：ruff（含 isort、flake8 规则集）。
- **类型**：mypy `--strict` 在 `core/` `store/` `agent/`，其余 `--check-untyped-defs`。
- **分层约束**：import-linter（见下），CI 必跑。
- **测试**：pytest，`core/` 高覆盖且不 mock LLM，`store/` 覆盖重放/撤销，`agent/` 少量冒烟。

---

## Forbidden Patterns

### 1. `core/` 依赖任何外部（最高优先级红线）

```python
# core/nag.py 里出现这些 import，CI 直接红：
import langchain_core    # 禁
from agent import ...   # 禁
from store import ...    # 禁
from collectors import ...# 禁
import requests, httpx    # 禁（网络）
import sqlite3            # 禁（IO）
```

**为什么**：`core/` 是判定层，要可单测、可离线、可复现。一旦它依赖 LLM/网络/DB，"该催谁"这类判定就变成不可测、不稳定、无法离线运行，ADR-0003 整个塌掉。

import-linter 规则（`pyproject.toml` 片段）：
```ini
[tool.importlinter]
root_package = "core"
include_external_packages = true   # forbidden_modules 含外部包时必须开

[[tool.importlinter.contracts]]
name = "core must not import agent/store/api/collectors/scheduler or langchain"
type = "forbidden"
source_modules = ["core"]
forbidden_modules = [
    "agent", "store", "api", "collectors", "scheduler",
    # langchain 生态以多个独立发行包存在（langchain_core / langchain_openai / langgraph），
    # 各自是顶层模块，必须逐一禁止——只写 "langchain" 拦不住 langchain_core。
    "langchain", "langchain_core", "langchain_openai", "langgraph",
]
```

> **踩坑记录**：`forbidden_modules` 里只写 `langchain` 是不够的——`langchain_core`、`langchain_openai`、`langgraph` 是各自独立的顶层模块，只禁 `langchain` 时它们都能漏进 `core/` 而 contract 误报 KEPT。必须逐一列举。改完要写一个临时 import 文件实测验证 contract 真的会 broken，再删掉。

### 2. 直接修改投影表

见 database-guidelines。所有写走 `events.append`。

### 3. `core/` 读系统时钟

```python
from datetime import now  # 禁 in core
datetime.now()             # 禁 in core
```
当前时间必须作 `now` 参数传入。**为什么**：单测要能伪造时钟（M2 验收全靠这个）。

### 4. git 写子命令

`collectors/git.py` 白名单外子命令一律拒绝，见 ADR-0004。代码层不可达。

### 5. agent 自主发起对外写操作

Gerrit +2 / abandon / rebase、删任务，必须经确认流（`request_confirm`）。LLM 在代码层不可绕过。

---

## Required Patterns

- `core/` 函数接收 `now: datetime` 参数。
- 所有状态写 = `events.append(kind=..., actor=..., payload=...)`。
- 外部调用（LLM/git/Gerrit）包 try 转 `ProviderUnavailable`/`CollectorError`。
- Tool 注册时声明授权级别（read / write / confirm）。
- pydantic 模型做请求/响应/事件 payload 校验。

---

## Testing Requirements

| 层 | 要求 |
|---|---|
| `core/` | 高覆盖，**不 mock LLM**（本就不依赖）。时间边界用伪造时钟。覆盖率目标 ≥ 90%。 |
| `store/` | 覆盖 append、重放、撤销、投影重建、迁移幂等。 |
| `agent/` | 少量端到端冒烟，mock provider。不追求高覆盖——判定逻辑在 core。 |
| `collectors/` | git 白名单越权测试（尝试 `reset --hard` 必须被拒）。 |
| `api/` | 端点冒烟 + token 鉴权测试。 |

---

## Code Review Checklist

- [ ] 新逻辑进对层了吗？（判定进 core，IO 进对应层）
- [ ] `core/` 有没有偷偷 import 外部？（CI 会拦，但 review 先看）
- [ ] 写操作走 events.append 了吗？
- [ ] 外部调用包 try 了吗？
- [ ] 对外写操作有确认护栏吗？
- [ ] 时间相关逻辑用 now 参数了吗，还是读了系统时钟？
- [ ] 新事件 kind 加到重放逻辑里了吗？
