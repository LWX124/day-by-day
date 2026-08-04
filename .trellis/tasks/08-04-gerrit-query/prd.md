# Gerrit SSH 查询器

## Goal

实现 Gerrit 2.8.4 的 SSH CLI 查询，产出 change 状态 evidence。

## Requirements

- ssh gerrit.client.weibo.cn gerrit query --format=JSON --current-patch-set 查询
- 适配 2.8.4 输出格式（stats 行 + 多 JSON 对象）
- 查询 owner:self status:open（我提的未合并）
- 查询 reviewby:self（待我评审）
- change merged 状态作为比本地 commit 更强的完成证据

## Acceptance Criteria

- [ ] 查询 owner:self 返回我的未合并 change
- [ ] 查询待评审 change 正常
- [ ] change merged 状态正确解析
- [ ] SSH 失败（断内网）降级不崩

## Notes

- 环境已验证：2.8.4/port 29419/user weixi1/BatchMode 通过
- REST API 残缺只走 SSH CLI
