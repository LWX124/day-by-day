# Process Supervision

> Swift 外壳守护 Python 后端的契约。`BackendSupervisor` 是 spawn / 退避重启 / 健康检查 / 日志汇聚的唯一Owner。

---

## Overview

`DayByDayApp` 启动时拉起 `BackendSupervisor`，它作为父进程 spawn `uv run python -m api` 子进程，探活 `/health`，崩溃按退避序列重启，连续失败切 worried。所有契约见 design.md §2，本规范补 design.md 没写明的**跨进程环境陷阱**与**重启路径不变式**。

---

## Scenario: GUI 环境 spawn 子进程

### 1. Scope / Trigger

Swift 外壳用 `Process` spawn 任何外部命令（`uv`、未来可能的 `git`、`ssh`）时触发。**GUI app 经 launchd 启动，PATH 是 macOS 默认最小集 `/usr/bin:/bin:/usr/sbin:/sbin`，不含用户 shell 的 `~/.local/bin`、`~/.cargo/bin`、`/opt/homebrew/bin`。** 凡是 `which` 能找到但 GUI 找不到的命令，都会 `code=127`（command not found）。

### 2. Signatures

```swift
// 探测可执行文件绝对路径，命中第一个存在的即返回，全失败返回 nil
private func resolveExecutableURL(candidates: [URL]) -> URL?

// 子进程环境：候选目录前置到 PATH，保留系统默认兜底
private func augmentedEnvironment() -> [String: String]
```

`uv` 候选顺序（`resolveUvURL` 实现）：
1. `~/.local/bin/uv`（uv 官方默认，`homeDirectoryForCurrentUser` 展开）
2. `~/.cargo/bin/uv`（cargo 安装）
3. `/usr/local/bin/uv`（Homebrew Intel / 手动）
4. `/opt/homebrew/bin/uv`（Homebrew Apple Silicon）
5. `which uv` 兜底（开发期从 shell 启动时 PATH 含 uv）

### 3. Contracts

- **`executableURL`**：用探测到的绝对路径，**不用 `/usr/bin/env <cmd>`**（env 仍依赖 PATH，GUI 环境会失败）。
- **`arguments`**：用绝对路径时去掉命令名首位（`["run", "python", ...]` 而非 `["uv", "run", ...]`）。
- **`environment`**：必须显式设置。把候选目录前置到 PATH，末尾保留系统默认 `/usr/bin:/bin:/usr/sbin:/sbin`。不设则继承父进程 GUI 的窄 PATH，`uv run` 内部 fork 的子进程同样找不到工具。
- **`currentDirectoryURL`**：设为 `daybyday-agent/`（`uv run` 需在项目目录解析 `pyproject.toml`）。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| 候选路径全不存在 + `which` 兜底失败 | `health = .failed`，写"未找到 uv，请安装：..."日志，**直接 return，不调 `scheduleRestart`** |
| `Process.run()` 抛错 | `appendLog("spawn 失败")` + `scheduleRestart()`（可重试错误） |
| 子进程退出 `code=127` | `handleTermination` → `scheduleRestart()`（但 127 是确定性失败，会连续 5 次后切 worried；理想情况应在 spawn 前探测拦截，不走到这） |
| 子进程正常退出（shutdown 调用） | `guard health != .failed` 拦住，不重启 |

**关键区分**：探测失败（uv 根本没装）是**确定性失败**，重试无意义，快速失败；`Process.run()` 抛错（端口占用等）是**可重试失败**，走退避。

### 5. Good/Base/Bad Cases

- **Good**：`~/.local/bin/uv` 存在且可执行 → 用绝对路径 spawn，子进程 PATH 含 `~/.local/bin`，后端正常起来。
- **Base**：从 Xcode Run 启动（继承 shell PATH）→ 候选探测命中或 `which` 兜底命中，行为与 Good 一致。
- **Bad**：用户没装 uv → 4 个候选 + which 全失败 → 直接 `.failed` + 安装提示，**不**出现 5 次 127 退避噪音。

### 6. Tests Required

- **uv 存在**：从 Finder/Dock 双击启动 app（模拟 launchd 环境），断言后端进程拉起、日志无 `code=127`、宠物不切 worried。
- **uv 缺失**：临时改名 `~/.local/bin/uv`，启动 app，断言日志出现"未找到 uv"、**不**出现退避序列、宠物直接 worried。
- **PATH 注入**：断言子进程 `environment["PATH"]` 含 `~/.local/bin`（可在后端启动时 echo `$PATH` 验证）。

### 7. Wrong vs Correct

#### Wrong

```swift
p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
p.arguments = ["uv", "run", "python", "-m", "api", ...]
// 不设 p.environment
// GUI 启动 → env 找不到 uv → code=127 → 5 次退避 → worried
```

#### Correct

```swift
guard let uvURL = resolveUvURL() else {
    appendLog("未找到 uv，请安装：curl -LsSf https://astral.sh/uv/install.sh | sh\n")
    health = .failed
    return  // 确定性失败，不退避
}
p.executableURL = uvURL
p.arguments = ["run", "python", "-m", "api", ...]
p.environment = augmentedEnvironment()  // 显式注入扩展 PATH
```

---

## Scenario: 退避重启的单一重启路径

### 1. Scope / Trigger

`BackendSupervisor` 有两个可能触发重启的源：`handleTermination`（子进程退出）和 `startHealthCheck` 超时（15s 没探到 `/health`）。两者都会调 `scheduleRestart()`，若不约束会**双重计数 + 孤儿进程 + 状态损坏**。

### 2. 不变式

**`scheduleRestart()` 只能有一个调用入口：`handleTermination`。** 健康检查超时不直接重启，而是 `process?.terminate()` 让子进程退出，由 `handleTermination` 单点接管。

### 3. 双重计数的问题链

若超时分支直接调 `scheduleRestart()`：
1. `scheduleRestart()` 立即 `restartAttempts++`，延迟后 `spawn()` 创建**新**进程覆盖 `self.process`。
2. 卡住的**旧**进程仍在跑，迟早退出 → `terminationHandler` → `handleTermination`：置 `self.process = nil`（清的是**新**进程引用）→ cancel healthCheckTask（取消的也是**新**进程的检查）→ 再 `scheduleRestart()`，`restartAttempts` 又 ++。
3. 一次超时变成两次重启计数；新进程的健康检查被误取消、引用被清；旧进程无人杀，孤儿残留。

### 4. Validation & Error Matrix

| 条件 | 行为 |
|---|---|
| 健康检查 15s 超时，进程仍在 | `guard process != nil` → `process?.terminate()` → 等 `handleTermination` 接管 |
| 健康检查超时，但进程已被 `handleTermination` 置 nil（如 127 立即退出） | `guard process != nil` 拦住，直接 return，不重复处理 |
| `handleTermination` 触发 | cancel healthCheckTask → `guard health != .failed` → `scheduleRestart()`（唯一计数点） |
| `shutdown()` 主动退出 | health 置 `.failed` 前置或 `handleTermination` 的 `guard` 拦截，不重启 |

### 5. Tests Required

- **kill 后恢复**：手动 `kill` 后端进程，断言 8s 内（退避 1s + 启动 + 探活）自动恢复，`restartAttempts` 只 +1。
- **超时重启**：让后端启动但 `/health` 不响应（如改路由），断言 15s 后走 `terminate()` → `handleTermination` → 重启，`restartAttempts` 只 +1，无孤儿进程。
- **连续失败上限**：连续 5 次失败后断言 `health = .failed`、宠物 worried、不再重启。

### 6. Wrong vs Correct

#### Wrong

```swift
// startHealthCheck 超时分支
guard self.process != nil else { return }
self.appendLog("健康检查超时，后端未就绪\n")
self.scheduleRestart()  // 直接重启 → 双重计数 + 旧进程孤儿
```

#### Correct

```swift
guard self.process != nil else { return }
self.appendLog("健康检查超时，后端未就绪，终止旧进程\n")
self.process?.terminate()  // 让 handleTermination 单点接管重启
```

---

## Common Mistakes

- **用 `/usr/bin/env <cmd>` spawn**：GUI 环境下 env 仍受窄 PATH 限制，必 127。用绝对路径 + 注入 PATH。
- **不设 `p.environment`**：继承 GUI 窄 PATH，`uv run` 内部 fork 的子进程同样找不到工具。
- **健康检查超时直接 `scheduleRestart()`**：和 `handleTermination` 双重计数，且旧进程成孤儿。走 `terminate()` 单点接管。
- **`handleTermination` 不 cancel healthCheckTask**：进程已死，健康检查超时分支仍可能跑，双重触发。补 `healthCheckTask?.cancel()`。
- **`~` 字符串拼接**：`"~/.local/bin/uv"` 不会展开。用 `FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent`。

---

## Related

- design.md §2：spawn 契约、退避序列 [1,2,4,8,30]、token 传递、端口分配。
- ADR-0001：双进程架构（Swift 外壳 + Python 后端）。
- [State Management](./state-management.md)：后端权威状态与降级展示。
