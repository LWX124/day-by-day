"""后端启动入口：`python -m api --token <token> [--host 127.0.0.1] [--port 0]`。

对应 PRD「token 由 Swift 启动时生成并以命令行参数传入，不落盘不进环境变量」与
design.md §2「不走环境变量」。token 经命令行传入，存 app.state.api_token，
不读环境变量、不落盘。

默认 host=127.0.0.1（design.md §2 只 bind loopback），port=0 由 OS 分配随机高位端口。
"""

from __future__ import annotations

import argparse
import logging
import secrets
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m api", description="daybyday-agent 后端")
    parser.add_argument(
        "--token",
        default=None,
        help="API 鉴权 token（PRD: 命令行传入，不落盘不进环境变量）。"
        "缺省时生成随机 token 并打到 stderr。",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="绑定地址（design.md §2: 只 bind 127.0.0.1）。默认 127.0.0.1。",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="绑定端口，0 = OS 分配随机高位端口（design.md §2）。默认 0。",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("daybyday-agent")

    token = args.token
    if token is None:
        # 开发期未传：生成并打到 stderr，Swift 生产路径必传。
        token = secrets.token_urlsafe(32)
        print(f"[daybyday-agent] generated dev token: {token}", file=sys.stderr)
        log.warning("未收到 --token，已生成开发用随机 token（生产应由 Swift 注入）")

    # 延迟 import：create_app 会 init_db，放在 argparse 之后避免无参启动时副作用。
    import uvicorn

    from api.app import create_app

    app = create_app(token=token)

    # port=0 让 OS 选随机高位端口。Swift 启动时若需知道端口，从 stdout/日志读。
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    log.info("starting backend on %s:%s (token=%s...)", args.host, args.port, token[:6])
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
