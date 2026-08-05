# BackendSupervisor uv 路径探测修复（GUI 环境启动 127）

## Goal

修复从 Xcode/Dock 启动 GUI app 时，BackendSupervisor 用 `/usr/bin/env uv` spawn 后端导致 `code=127`（command not found）、连续 5 次退避后宠物切 worried 的问题。根因：GUI 进程的 PATH 是 macOS 默认最小集（`/usr/bin:/bin:/usr/sbin:/sbin`），不含 `uv` 所在的 `~/.local/bin` 等用户安装路径。

## Background

- 现状（`BackendSupervisor.swift:85-87`）：`p.executableURL = /usr/bin/env`，`arguments = ["uv", "run", "python", "-m", "api", ...]`。依赖 PATH 能找到 `uv`。
- GUI app 经 launchd 启动，无用户 shell 的 PATH（已验证 `launchctl getenv PATH` 为空）。
- `uv` 实际位于 `/Users/<user>/.local/bin/uv`（官方安装默认路径）。
- 连带问题（本任务范围内）：即便修了 127，`probeHealth()` 仍 `return true`（line 176），`resolvedPort` 写死 18080（line 170），而 spawn 传 `port=0` 让 OS 随机分配，stdout 端口解析是 TODO（line 101、152-167）。修完 127 会出现"后端起来了但健康检查连不上"的假象，需一并处理。

## Requirements

- **uv 路径探测**：spawn 前按序探测候选路径，命中则用绝对路径作为 `executableURL`，不再依赖 `env` + PATH：
  - `~/.local/bin/uv`（uv 官方默认）
  - `~/.cargo/bin/uv`（cargo 安装）
  - `/usr/local/bin/uv`（手动/Homebrew Intel）
  - `/opt/homebrew/bin/uv`（Homebrew Apple Silicon）
  - `which uv` 兜底（开发期从 shell 启动时仍可用）
- **子进程 PATH 兜底**：把上述目录也注入子进程环境 `PATH`，避免 `uv run` 内部再 fork 子进程时同样找不到工具。
- **探测失败快速失败**：所有候选都找不到时，直接 `health = .failed`，写明确日志 `未找到 uv，请安装：curl -LsSf https://astral.sh/uv/install.sh | sh`，**不进入退避重试**（重试无意义，127 是确定性失败）。
- **端口解析落实**：从 uvicorn stdout 日志解析实际监听端口（`Uvicorn running on http://127.0.0.1:PORT`），写入 `resolvedPort`，`probeHealth()` 用该端口真实探 `/health`。
- **健康检查超时走重启**：15s 内端口未解析出或 `/health` 不通，按原退避序列重启（这条逻辑已存在，确保端口修复后路径正确）。
- **不破坏开发期从 shell 启动**：从 Xcode 跑（继承 shell PATH）时行为不变。

## Acceptance Criteria

- [ ] 从 Xcode Run 启动 app，后端正常拉起，日志无 `code=127`，宠物不切 worried
- [ ] 从 Dock/Finder 双击启动 app（模拟用户真实启动），后端正常拉起
- [ ] `uv` 不存在时（临时改名 `~/.local/bin/uv` 验证），日志出现明确的"未找到 uv"提示，**不**出现 5 次退避，宠物直接 worried
- [ ] 后端起来后健康检查真实探 `/health`，端口为 uvicorn 实际报告的端口而非写死的 18080
- [ ] 手动 kill 后端进程，8s 内自动恢复（验证退避重启路径未被破坏）

## Notes

- 候选路径含 `~`，需用 `FileManager.default.homeDirectoryForCurrentUser` 展开，不能用字符串拼接。
- 端口解析用正则匹配 `Uvicorn running on http://127.0.0.1:(\d+)`，匹配到即停止读 stdout。
- 这是 `08-04-backend-supervisor`（已 archive）的回归修复，不改变原设计（spawn `uv run`、退避序列、token 传递），只补 GUI 环境的路径假设。
