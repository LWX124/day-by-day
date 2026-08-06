#!/usr/bin/env bash
# 编译并启动 DayByDay.app（不打开 Xcode）。
#
# 用 `open` 启动 .app，让 app 以普通 GUI 方式经 launchd 拉起，
# 继承 macOS 默认窄 PATH（/usr/bin:/bin:/usr/sbin:/sbin）——
# 这正是 backend-supervisor-uv-path 修复要验证的场景：
# GUI 环境下 uv 不在 PATH，靠 resolveUvURL() 探测绝对路径拉起后端。
#
# 用法：
#   ./run.sh            # Debug 编译并启动
#   ./run.sh build      # 只编译不启动
#   ./run.sh log        # 跟随后端日志（agent.log）
#   ./run.sh kill       # 杀掉运行中的 DayByDay

set -euo pipefail

PROJECT="DayByDay.xcodeproj"
SCHEME="DayByDay"
CONFIGURATION="Debug"
APP_NAME="DayByDay.app"
APP_PROCESS_NAME="${APP_NAME%.app}"
BUNDLE_ID="io.daybyday.app"

# 日志路径（与 BackendSupervisor 写入一致）
LOG_DIR="$HOME/Library/Application Support/DayByDay/logs"
LOG_FILE="$LOG_DIR/agent.log"

cmd="${1:-run}"

build() {
  echo "▸ 编译 $SCHEME ($CONFIGURATION)..."
  # -quiet 只输出 warning/error； DerivedData 用默认位置
  xcodebuild \
    -project "$PROJECT" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION" \
    -derivedDataPath build/DerivedData \
    build \
    2>&1 | sed 's/^/  /'
}

# 从 DerivedData 定位 .app 产物
app_path() {
  local app
  app="$(find build/DerivedData/Build/Products/$CONFIGURATION -maxdepth 1 -name "$APP_NAME" -type d 2>/dev/null | head -1)"
  if [ -z "$app" ]; then
    echo "✗ 找不到 $APP_NAME 产物" >&2
    exit 1
  fi
  echo "$app"
}

# 先按 bundle id 请求 AppKit 正常退出，让 applicationWillTerminate 回收后端；
# 3 秒仍未退出时，才按精确进程名兜底终止。
stop_app() {
  if ! pgrep -x "$APP_PROCESS_NAME" >/dev/null 2>&1; then
    return 1
  fi

  osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
  for _ in {1..30}; do
    if ! pgrep -x "$APP_PROCESS_NAME" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done

  pkill -x "$APP_PROCESS_NAME" 2>/dev/null || true
  for _ in {1..10}; do
    if ! pgrep -x "$APP_PROCESS_NAME" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done

  pkill -KILL -x "$APP_PROCESS_NAME" 2>/dev/null || true
  return 0
}

case "$cmd" in
  build)
    build
    echo "✓ 编译完成"
    ;;
  run)
    build >/dev/null 2>&1 || { echo "✗ 编译失败，重跑 ./run.sh build 看详情"; exit 1; }
    APP="$(app_path)"
    echo "▸ 启动 $APP"
    # 先杀掉旧实例，避免多开
    stop_app || true
    open "$APP"
    echo "✓ 已启动（GUI 模式，继承 launchd 窄 PATH）"
    echo "  日志: $LOG_FILE"
    echo "  跟随日志: ./run.sh log"
    echo "  停止: ./run.sh kill"
    ;;
  log)
    if [ ! -f "${LOG_FILE}" ]; then
      echo "日志还不存在: ${LOG_FILE}（app 启动后由 BackendSupervisor 创建）"
      exit 1
    fi
    echo "▸ 跟随 ${LOG_FILE}（Ctrl-C 退出）"
    tail -f "${LOG_FILE}"
    ;;
  kill)
    if stop_app; then
      echo "✓ 已停止 DayByDay"
    else
      echo "（没有运行中的实例）"
    fi
    ;;
  *)
    echo "用法: ./run.sh [build|run|log|kill]"
    exit 1
    ;;
esac
