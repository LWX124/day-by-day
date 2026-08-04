# sprite sheet 接入与状态机

## Goal

用 SpriteSheetPetRenderer 替换占位实现，状态机对接 Emotion State。

## Requirements

- SpriteSheetPetRenderer 实现 PetRenderer 协议
- 加载 sprite sheet PNG + JSON 帧描述（帧尺寸/帧数/fps/循环点）
- Emotion State → sprite 状态映射
- 动作事件（nod/cheer/special）触发对应动画
- 依赖 sprite-assets 任务产出

## Acceptance Criteria

- [ ] 占位实现被 sprite 实现替换，其余代码不改
- [ ] 切换 Emotion State 时 sprite 平滑切换
- [ ] 动作事件触发对应帧动画

## Notes

- 依赖 sprite-assets 产出就位
- PetRenderer 协议在 M0 spike 已定义，保证可互换
