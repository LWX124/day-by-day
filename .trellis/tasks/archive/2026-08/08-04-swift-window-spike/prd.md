# Swift 窗口 spike

## Goal

用最小代码验证透明无边框 + 始终置顶 + 跨 Space + 点击穿透 + 不抢焦点的窗口组合可行，再决定铺代码。

## Requirements

- 30 行级 spike：NSPanel + .floating + canJoinAllSpaces/stationary + 透明无边框
- 验证：窗口在所有 Space 可见、不被其他窗口遮挡、不抢焦点、可拖拽
- CelebrationOverlay spike：全屏 + .screenSaver level + ignoresMouseEvents，验证点击穿透到下方编辑器
- LSUIElement=true 验证 Dock 图标隐藏
- spike 通过后把窗口配置固化成可复用代码

## Acceptance Criteria

- [ ] 宠物窗口在多桌面 Space 切换时始终可见
- [ ] 全屏 overlay 播放时能在下方编辑器正常打字
- [ ] app 不在 Dock 显示图标
- [ ] spike 代码可独立运行验证（不必接后端）

## Notes

- 这一期唯一有未知的地方就是窗口组合，先 spike 再铺代码能避免返工
- PetRenderer 占位实现（SF Symbols + SwiftUI 动画）在本任务一并搭好，让宠物能动
