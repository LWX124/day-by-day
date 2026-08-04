# M3 情绪反馈

## Goal

完成任务有分级特效（满屏烟花），宠物有情绪状态机，sprite 正式接入。

参考：`design.md §5.3-§5.4, §8`

## 子任务依赖

- celebration-tier/emotion-state 纯函数先行
- celebration-overlay 依赖 swift-window-spike(M0)
- sprite-integration 依赖 sprite-assets

## Acceptance Criteria

- [ ] 四档特效各自触发，Tier3-4 期间能正常打字
- [ ] 拖一个月的 M 任务完成得 Tier4
- [ ] Emotion State 纯函数推导不经 LLM
- [ ] sprite 替换占位实现其余代码不改

## Notes

- sprite 素材从 M0 第一天并行生产，M3 前就位
- 情绪价值峰值在'拖很久终于干掉'
- 逾期完成不降档
