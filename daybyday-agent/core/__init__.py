"""core 纯函数域。

最核心的架构红线（spec/backend/quality-guidelines.md §1）：
本包禁 import 任何 agent/store/api/collectors/scheduler 模块及 langchain*。
所有判定（该催谁、Tier、EmotionState、统计）住在这里，可单测、可离线、可复现。

函数签名一律接收已加载的内存数据 + now 参数，不读系统时钟、不开数据库连接。
"""
