"""帆布浸渍防水台业务规则。"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from .models import ClothRoll, DipRun

MIN_CURE_HOURS_FOR_CURED = Decimal("12")


def latest_dip_run(roll: ClothRoll) -> DipRun | None:
    return roll.dip_runs.order_by("-started_at", "-id").first()


def can_revert_to_raw(roll: ClothRoll) -> tuple[bool, str]:
    """
    浸渍中卷拨回原布的前提：管理员已在专页确认「冷却已满」。
    已固化卷不经过此闸门（另由状态流转约束处理）。
    """
    if roll.status == ClothRoll.STATUS_DIPPING and not roll.cool_down_full:
        return False, "该卷冷却未满，不能拨回原布；请先由管理员在布卷专页勾选「冷却已满」"
    return True, ""


class RollStateConflict(RuntimeError):
    """卷已不是预期状态（典型：并发下另一笔已先拨回）。"""


@transaction.atomic
def revert_dipping_to_raw(roll_id: int) -> ClothRoll:
    """
    把浸渍中卷拨回原布并清掉冷却已满标记。

    用单条条件 UPDATE 完成闸门+互斥：status=dipping 且 cool_down_full=True
    才会更新。冷却未满 -> ValueError；卷不存在 -> DoesNotExist；
    并发败者（状态已被另一笔改掉）-> RollStateConflict。
    """
    updated = ClothRoll.objects.filter(
        pk=roll_id, status=ClothRoll.STATUS_DIPPING, cool_down_full=True
    ).update(status=ClothRoll.STATUS_RAW, cool_down_full=False)
    if updated:
        return ClothRoll.objects.get(pk=roll_id)

    # 未命中：区分「冷却未满」与「状态已被并发改掉」。
    roll = ClothRoll.objects.get(pk=roll_id)
    ok, msg = can_revert_to_raw(roll)
    if not ok:
        raise ValueError(msg)
    raise RollStateConflict("该卷状态已变更，拨回未生效（可能已被他人操作）")


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
