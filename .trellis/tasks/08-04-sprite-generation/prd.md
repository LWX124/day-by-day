# sprite sheet 生成与帧描述

## Goal

按锁定风格批量生成所有状态/动作的 sprite sheet + JSON 帧描述。

## Requirements

- 每状态/动作生成 @2x sprite sheet PNG
- 配套 JSON 帧描述：帧尺寸/帧数/fps/循环点
- 放 assets/ 目录
- 交付给 sprite-integration 任务

## Acceptance Criteria

- [ ] 所有状态/动作都有 sprite sheet
- [ ] JSON 帧描述完整可被 SpriteSheetPetRenderer 加载
- [ ] 风格一致（符合 style-lock）

## Notes

- 交付物被 sprite-integration 消费
- M3 前必须就位（plan 并行启动约束）
