// PetCommand.swift
// 后端推送给前端的命令枚举（design.md §2 Python → Swift SSE 协议）。
// M1：意图对话框相关命令。

import Foundation

/// 后端 → Swift 的 PetCommand 推送。
enum PetCommand: Equatable {
    /// 设置宠物情绪
    case setEmotion(EmotionState)
    /// 弹气泡消息
    case bubble(text: String, ttl: TimeInterval, quickReplies: [String]?)
    /// 播放庆祝特效
    case celebrate(tier: Int, text: String)
    /// 系统通知
    case notify(title: String, body: String)
    /// 打开面板到指定分区
    case openPanel(section: String)
    /// 请求二次确认
    case requestConfirm(actionId: String, title: String, detail: String)
    /// 宠物徽标
    case badge(count: Int)

    // MARK: - Intent Dialog Commands

    /// 本地触发：打开意图对话框
    case openIntentDialog
    /// 后端响应：展示意图执行结果
    case intentResponse(text: String, actions: [IntentAction])
    /// 后端追问：需要用户澄清
    case clarify(question: String)
}

/// 意图响应动作按钮
struct IntentAction: Equatable, Codable {
    let type: String
    let payload: [String: String]?
}
