# 并行流 sprite 素材

## Goal

从 M0 第一天并行启动，M3 前交付全部 sprite sheet + 帧描述。

参考：`design.md §8 PetRenderer`

## 子任务依赖

- sprite-state-list→sprite-style-lock→sprite-generation
- 与 M0-M2 并行，不阻塞主线
- M3 前必须就位

## Acceptance Criteria

- [ ] 状态/动作清单覆盖全部触发
- [ ] 风格锁定无漂移
- [ ] 所有 sprite sheet + JSON 帧描述交付给 sprite-integration

## Notes

- 这是长周期工作流，必须早启动
- 风格先锁死防返工
- 交付物被 sprite-integration(M3) 消费
