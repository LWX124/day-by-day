"""agent 层：LLM 与 LangGraph。

只做三件事：把自然语言解析成结构化命令、把 core 算好的事实组织成人话、多轮对话。
判定不经过 LLM（ADR-0003），所有判定在 core/。
"""
