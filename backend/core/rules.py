"""帆布浸渍防水台业务规则。"""

from __future__ import annotations

from decimal import Decimal

from .models import ClothRoll, DipRun

MIN_CURE_HOURS_FOR_CURED = Decimal("12")


def latest_dip_run(roll: ClothRoll) -> DipRun | None:
    return roll.dip_runs.order_by("-started_at", "-id").first()


def can_mark_roll_cured(roll: ClothRoll) -> tuple[bool, str]:
    """
    布卷转为「已固化」(cured) 的前提：
    最近一条浸渍记录的固化时长已记录，且 >= 12 小时。
    """
    latest = latest_dip_run(roll)
    if latest is None:
        return False, "该布卷尚无浸渍记录，不能标记为已固化"
    if latest.cure_hours is None:
        return False, "最近浸渍记录尚未填写固化时长，不能标记为已固化"
    if latest.cure_hours < MIN_CURE_HOURS_FOR_CURED:
        return (
            False,
            f"最近浸渍固化时长 {latest.cure_hours} 小时低于 {MIN_CURE_HOURS_FOR_CURED} 小时，不能标记为已固化",
        )
    return True, ""


def can_return_roll_to_raw(roll: ClothRoll) -> tuple[bool, str]:
    """
    布卷拨回「原布」(raw) 的前提：
    仅当卷处于「浸渍中」时受冷却约束——专页「冷却已满」必须已勾选。
    标「已固化」及已固化卷拨回均不看这勾。
    """
    if roll.status == ClothRoll.STATUS_DIPPING and not roll.cooling_done:
        return (
            False,
            "冷却未满：浸渍中的布卷须由管理员在冷却勾专页勾选「冷却已满」后才能拨回原布",
        )
    return True, ""
