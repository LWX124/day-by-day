"""store 层测试：事件流 append / 重放 / 撤销 / 投影重建 / 迁移幂等。

用临时 db 文件（tmp_path），绝不碰真实 DB_PATH（quality-guidelines）。
"""
