"""store 层：事件流 + 投影。唯一事实来源（ADR-0002）。

所有状态写走 events.append，不直接改投影表。撤销靠 EventUndone。
"""
