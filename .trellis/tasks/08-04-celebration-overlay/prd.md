# CelebrationOverlay 全屏窗口

## Goal

实现 Tier 3–4 的全屏透明 overlay 烟花窗口。

## Requirements

- 全屏 NSWindow，.screenSaver level，ignoresMouseEvents=true，跨 Space
- SpriteKit 粒子烟花：Tier 3 约 3s，Tier 4 约 8s + 大字文案 + 音效
- 播放完销毁窗口不残留
- 不抢焦点、点击穿透到下方编辑器

## Acceptance Criteria

- [ ] Tier 3 播放 3s 期间能正常打字
- [ ] Tier 4 播放 8s + 大字 + 音效
- [ ] 播完窗口销毁无残留
- [ ] 跨 Space 可见
- [ ] CPU 峰值可接受

## Notes

- 窗口配置在 swift-window-spike 已验证
- 这是满屏烟花的核心载体
