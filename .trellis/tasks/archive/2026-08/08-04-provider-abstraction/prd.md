# Provider 抽象与配置

## Goal

实现 LLM Provider 抽象与 config.toml 路由解析，支持百炼/DeepSeek/微博内部网关，OpenAI-compatible 走 ChatOpenAI。

## Requirements

- Provider 接口：统一 chat/结构化输出/tool calling 三能力
- config.toml 解析：[llm] default/fallback + [llm.providers.*] kind/base_url/model/api_key_env
- openai_compatible 适配：ChatOpenAI(base_url=..., model=...)，key 从环境变量读
- 失败 fallback 链：default 失败自动切 fallback 列表
- 微博内部网关：协议待确认，兼容则同上，不兼容预留 BaseChatModel 子类位
- 无 key 时返回不可用标记，触发降级模式

## Acceptance Criteria

- [ ] 配置百炼 key 后能完成一次 chat 调用
- [ ] default 失败时自动用 deepseek 重试
- [ ] 清空所有 key 后 Provider 返回 unavailable，不抛异常

## Notes

- 微博网关 base_url/协议是外部待确认项，不阻塞本任务
- 数据边界不设限（ADR-0004），但保留 routing 配置位
