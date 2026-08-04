# Type Safety

> Swift 类型与前后端契约。

---

## Overview

Swift 强类型，重点在**前后端契约对齐**：Swift 侧模型用 `Codable` 与后端 JSON 对齐，PetCommand 枚举与后端严格一致。类型不匹配要在编译期或解码期暴露，不留运行时隐患。

---

## Type Organization

- 共享模型放 `Models/`：`Task`、`Schedule`、`EmotionState`、`TodayView`，与后端 pydantic 模型字段对齐。
- `PetCommand` 放 `App/PetCommand.swift`，是前后端契约核心。
- 窗口局部类型就近定义，不污染全局。

---

## Validation

- `Codable` 解码后端 JSON，`DecodingError` 必须处理——后端字段变更导致解码失败要降级展示，不崩。
- 用户输入（对话框文本）不做复杂本地校验，原样发后端，后端 `structured-extraction` 负责解析与置信度。
- `Schedule` 联合类型在 Swift 用 `enum` + associated values，与后端 `schedule_kind` 对齐。

```swift
enum Schedule: Codable {
    case oneShot
    case deadline(dueAt: Date)
    case recurring(rule: RecurRule, target: RecurTarget)
    case openended
}
```

---

## Common Patterns

- ID 类型：`TaskID`、`ProjectID` 用 `typealias` 别名（`String`），语义清晰。
- 时间：统一 `Date`，解码用 ISO8601 带时区 strategy。
- Optional：后端可空字段用 `Optional`，显式标注而非隐式解包。

---

## Forbidden Patterns

- **`Any` 类型**——用具体类型或泛型。
- **强制解包 `!`**（除 IBOutlet）——用 `guard let` / `??`。
- **隐式解包 Optional 传给后端**——可能传 nil 导致后端崩。
- **PetCommand 用字符串硬编码**——必须用枚举，与后端对齐时编译器帮你检查。
- **本地重新定义后端已有的判定枚举**（如自己定义 Tier 计算）——Tier 是后端算好推过来的，Swift 只接收。
