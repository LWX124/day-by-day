# Error Handling

> 后端是常驻子进程，错误策略围绕"不崩、不吞、可恢复"。

---

## Overview

错误分三类：**用户可恢复**（输入/配置问题）、**外部暂时不可用**（LLM/Gerrit/网络）、**内部不变式违反**（bug）。前两类降级处理保活，第三类快速失败并告警。

---

## Error Types

`common/errors.py` 定义：

- `DayByDayError`：基类。
- `UserError(DayByDayError)`：用户输入或配置问题（如非法 schedule 组合、找不到 Project）。返回 4xx，气泡提示用户。
- `ProviderUnavailable(DayByDayError)`：LLM provider 全部失败。触发降级模式，不崩。
- `CollectorError(DayByDayError)`：git/Gerrit 采集失败（断内网、权限）。记日志，evidence 缺失，不阻断复盘。
- `InvariantError(DayByDayError)`：内部不变式违反（如投影与事件流对不上）。**快速失败**，记 error 日志，后端重启。

---

## Error Handling Patterns

- **`core/` 不抛业务异常**：纯函数返回结果或 `Optional`/`Result`，错误条件由调用方处理。唯一例外是非法 schedule 组合，在写入层校验时抛 `UserError`。
- **外部调用必包 try**：`agent/providers.py`、`collectors/*.py` 调 LLM/git/Gerrit 必须捕获，转成 `ProviderUnavailable`/`CollectorError`，不让异常冒泡到调度层导致整个 scheduler 挂。
- **scheduler job 失败不连累其他 job**：每个 job 包独立 try，失败记 error，APScheduler 继续跑下个 job。
- **降级而非崩溃**：LLM 不可用 → 降级模式（ADR-0003）；Gerrit 不可用 → 跳过该 evidence；DB 不可用 → 这才是致命错误，后端退出由 BackendSupervisor 重启。

```python
# collectors/gerrit.py 范本
try:
    raw = subprocess.run([...], timeout=15, check=True, capture_output=True)
except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
    raise CollectorError(f"gerrit query failed: {e}") from e
```

---

## API Error Responses

统一 JSON：

```json
{"error": "user_error", "message": "schedule recurring 不允许有 due_at", "detail": null}
```

- `UserError` → 400
- `ProviderUnavailable` → 503（同时已切降级模式）
- `InvariantError` → 500
- 未预期异常 → 500 + error 日志（不回传 traceback 给前端）

---

## Common Mistakes

- **让外部异常冒泡到 scheduler**——一个 Gerrit 超时能让 hourly_tick 整个 job 链停摆。必须就地转 `CollectorError`。
- **`core/` 抛异常**——纯函数域不该有副作用，返回 `Result` 或让调用方处理。
- **吞异常只 log 不分类**——降级决策需要错误类型，统一用上面的类型。

## Intent Dialog Error Patterns

### LLM Unavailable → Clarify降级

`IntentParser` 调用 `providers.py` 时 LLM 全部不可用，捕获 `ProviderUnavailable` 后返回 `action: "clarify"` + 降级提示，不抛异常：

```python
# api/routes/intent.py
async def post_intent(request: IntentRequest) -> IntentResponse:
    try:
        result = await parser.parse(request.text)
    except ProviderUnavailable:
        # 降级：不崩，让用户用结构化方式重试
        return IntentResponse(
            action=IntentAction.clarify,
            message="LLM 暂不可用，请用结构化方式描述意图。",
        )
```

### JSON Decode Fail → Clarify降级

LLM 返回非预期格式（非 JSON / 字段缺失），捕获后同样降级为 `clarify`：

```python
# api/routes/intent.py
try:
    parsed = json.loads(content)
except (json.JSONDecodeError, KeyError) as e:
    logger.warning("intent_parse_failed", extra={"error": str(e), "raw": content[:200]})
    return IntentResponse(
        action=IntentAction.clarify,
        message="我没听懂，请再描述一下。",
    )
```

### Tool Execution Fail → Error 气泡

`ToolExecutor` 执行 Tool 失败（如参数校验不通过），将错误包装进 `IntentResponse` 展示在对话框：

```python
# api/routes/intent.py
try:
    result = await registry.invoke(intent, ctx, args)
except DayByDayError as e:
    return IntentResponse(
        action=IntentAction.execute,
        message=f"执行失败：{e.message}",
    )
```

### Session TTL Expired → 新 Session

`SessionManager` 中 session TTL 过期（默认 10 分钟），不报错，静默创建新 session：

```python
# api/routes/intent.py
session = manager.get_or_create(request.session_id)
# get_or_create 内部：过期则删旧建新，调用方无感知
```
