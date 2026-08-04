"""四个 schedule 的 nag 策略对象 + due_nags 聚合。

design.md §5.1 表：

| schedule | 触发条件 | 不触发的情况 |
| one_shot   | now - last_activity_at > idle_threshold(weight) | 有近期活动 |
| deadline   | due 前 lead_days(weight) 天、due 当天、逾期后每日一次 | 未到提醒窗口 |
| recurring  | 连续断签 ≥ 2 个应有 occurrence | 永不因"总时长"触发 |
| openended  | 距上次 review > 30 天 | 本月已 review 过 |

本模块只做 `due_nags` 候选计算（M0）。nag_count 升级与 Re-decision 终点
是 M2 escalation 任务，不在本任务范围。

纯函数，不读系统时钟（now 作参数传入），不碰 DB。策略对象统一实现
`candidates(ctx, now) -> list[NagCandidate]` 接口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from core.schedule import ScheduleKind, Weight, idle_threshold, lead_days

# openended 默认 review 周期（天）
OPENENDED_REVIEW_INTERVAL_DAYS = 30


@dataclass(frozen=True)
class NagTaskView:
    """nag 策略需要的任务视图。"""

    id: str
    schedule_kind: ScheduleKind
    weight: Weight
    status: str
    due_at: datetime | None
    last_activity_at: datetime | None
    last_reviewed_at: datetime | None  # 仅 openended 用
    nag_count: int = 0
    last_nagged_at: datetime | None = None


@dataclass(frozen=True)
class NagOccurrenceView:
    """recurring 断签判定需要的 occurrence 视图。"""

    task_id: str
    occurrence_date: date
    status: str  # pending | partial | done | skipped


@dataclass(frozen=True)
class NagCandidate:
    """一个 nag 候选。LLM 层据此组织语气，scheduler 层据此推 PetCommand。"""

    task_id: str
    schedule_kind: ScheduleKind
    reason: str  # 机器可读的理由标签，供 LLM 组织成文
    detail: str  # 人类可读补充


@dataclass(frozen=True)
class NagContext:
    """策略对象共享的上下文：所有任务 + 所有 occurrence + today。"""

    tasks: list[NagTaskView]
    occurrences: list[NagOccurrenceView]
    today: date


def _days_since(last: datetime | None, now: datetime) -> int | None:
    """last 为 None 返回 None；否则返回 (now - last).days。"""
    if last is None:
        return None
    return (now - last).days


# ---- 策略对象 ----


@dataclass(frozen=True)
class OneShotPolicy:
    """one_shot：now - last_activity_at > idle_threshold(weight) 触发。"""

    def candidates(self, ctx: NagContext, now: datetime) -> list[NagCandidate]:
        out: list[NagCandidate] = []
        for t in ctx.tasks:
            if t.schedule_kind is not ScheduleKind.ONE_SHOT:
                continue
            if t.status in ("done", "abandoned", "deferred"):
                continue
            if t.last_activity_at is None:
                # 从未活动过：视为 idle（创建后一直没动）
                out.append(
                    NagCandidate(
                        task_id=t.id,
                        schedule_kind=ScheduleKind.ONE_SHOT,
                        reason="one_shot_idle_never_active",
                        detail="从未活动",
                    )
                )
                continue
            idle_days = _days_since(t.last_activity_at, now)
            assert idle_days is not None
            threshold = idle_threshold(t.weight)
            if idle_days > threshold:
                out.append(
                    NagCandidate(
                        task_id=t.id,
                        schedule_kind=ScheduleKind.ONE_SHOT,
                        reason="one_shot_idle",
                        detail=f"已 {idle_days} 天无活动（阈值 {threshold} 天）",
                    )
                )
        return out


@dataclass(frozen=True)
class DeadlinePolicy:
    """deadline：due 前 lead_days 天、due 当天、逾期后每日一次；未到窗口不触发。"""

    def candidates(self, ctx: NagContext, now: datetime) -> list[NagCandidate]:
        out: list[NagCandidate] = []
        for t in ctx.tasks:
            if t.schedule_kind is not ScheduleKind.DEADLINE:
                continue
            if t.status in ("done", "abandoned", "deferred"):
                continue
            if t.due_at is None:
                continue
            td = ctx.today
            due_date = t.due_at.date()
            days_until_due = (due_date - td).days
            window = lead_days(t.weight)
            # 未到窗口（且非 due 当天/逾期）：不触发
            if days_until_due > window:
                continue
            # 逾期后每日一次：靠 scheduler 层用 last_nagged_at 去重（同一天不重复）。
            # 这里只算"该不该催"，不算"今天催过没"——后者由调用方在推送前过滤。
            if days_until_due < 0:
                reason = "deadline_overdue"
                detail = f"逾期 {-days_until_due} 天"
            elif days_until_due == 0:
                reason = "deadline_due_today"
                detail = "今天到期"
            else:
                reason = "deadline_approaching"
                detail = f"距到期 {days_until_due} 天（窗口 {window} 天）"
            out.append(
                NagCandidate(
                    task_id=t.id,
                    schedule_kind=ScheduleKind.DEADLINE,
                    reason=reason,
                    detail=detail,
                )
            )
        return out


@dataclass(frozen=True)
class RecurringPolicy:
    """recurring：连续断签 ≥ 2 个应有 occurrence 触发；永不因总时长触发。"""

    def candidates(self, ctx: NagContext, now: datetime) -> list[NagCandidate]:
        out: list[NagCandidate] = []
        # 按 task_id 聚合 occurrence
        occ_by_task: dict[str, list[NagOccurrenceView]] = {}
        for o in ctx.occurrences:
            occ_by_task.setdefault(o.task_id, []).append(o)
        for t in ctx.tasks:
            if t.schedule_kind is not ScheduleKind.RECURRING:
                continue
            if t.status in ("done", "abandoned"):
                continue
            occs = sorted(occ_by_task.get(t.id, []), key=lambda o: o.occurrence_date)
            # 算连续断签：从最近一个 occurrence 往前数，连续 pending/partial（未 done/skipped）的数量。
            # 只数"应有 occurrence"——即 occurrence_date <= today 的。
            today = ctx.today
            relevant = [o for o in occs if o.occurrence_date <= today]
            # 倒序数连续未完成
            streak = 0
            for o in reversed(relevant):
                if o.status in ("done", "skipped"):
                    break
                streak += 1
            if streak >= 2:
                out.append(
                    NagCandidate(
                        task_id=t.id,
                        schedule_kind=ScheduleKind.RECURRING,
                        reason="recurring_broken_streak",
                        detail=f"连续断签 {streak} 个 occurrence",
                    )
                )
        return out


@dataclass(frozen=True)
class OpenEndedPolicy:
    """openended：距上次 review > 30 天触发；本月已 review 过不触发。"""

    interval_days: int = OPENENDED_REVIEW_INTERVAL_DAYS

    def candidates(self, ctx: NagContext, now: datetime) -> list[NagCandidate]:
        out: list[NagCandidate] = []
        for t in ctx.tasks:
            if t.schedule_kind is not ScheduleKind.OPENENDED:
                continue
            if t.status in ("done", "abandoned"):
                continue
            last_review = t.last_reviewed_at
            if last_review is None:
                out.append(
                    NagCandidate(
                        task_id=t.id,
                        schedule_kind=ScheduleKind.OPENENDED,
                        reason="openended_never_reviewed",
                        detail="从未 review",
                    )
                )
                continue
            # 本月已 review 过：不触发（"本月"按 last_review 的年月与 today 的年月比）
            if (
                last_review.year == ctx.today.year
                and last_review.month == ctx.today.month
            ):
                continue
            days_since_review = (now - last_review).days
            if days_since_review > self.interval_days:
                out.append(
                    NagCandidate(
                        task_id=t.id,
                        schedule_kind=ScheduleKind.OPENENDED,
                        reason="openended_review_overdue",
                        detail=f"距上次 review {days_since_review} 天（阈值 {self.interval_days} 天）",
                    )
                )
        return out


# 四个策略对象的默认实例，供 due_nags 使用。
ONE_SHOT_POLICY = OneShotPolicy()
DEADLINE_POLICY = DeadlinePolicy()
RECURRING_POLICY = RecurringPolicy()
OPENENDED_POLICY = OpenEndedPolicy()


def due_nags(
    tasks: list[NagTaskView],
    occurrences: list[NagOccurrenceView],
    now: datetime,
    today: date | None = None,
) -> list[NagCandidate]:
    """聚合四个策略的候选。today 缺省取 now 的日期。"""
    td = today if today is not None else now.date()
    ctx = NagContext(tasks=tasks, occurrences=occurrences, today=td)
    out: list[NagCandidate] = []
    out.extend(ONE_SHOT_POLICY.candidates(ctx, now))
    out.extend(DEADLINE_POLICY.candidates(ctx, now))
    out.extend(RECURRING_POLICY.candidates(ctx, now))
    out.extend(OPENENDED_POLICY.candidates(ctx, now))
    return out


__all__ = [
    "DeadlinePolicy",
    "NagCandidate",
    "NagContext",
    "NagOccurrenceView",
    "NagTaskView",
    "OneShotPolicy",
    "OpenEndedPolicy",
    "RecurringPolicy",
    "due_nags",
]
