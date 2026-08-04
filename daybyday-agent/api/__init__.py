"""api 层：FastAPI 端点 + SSE。

端点：/intent /today /tasks /confirm /wake /events(SSE)。
只 bind 127.0.0.1，Bearer token 鉴权（token 由 Swift 启动时生成传入）。
"""
