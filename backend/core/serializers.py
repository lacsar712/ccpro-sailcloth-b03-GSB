from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from accounts.models import User

from .models import ClothRoll, DipRun, Loft
from .rules import can_mark_roll_cured


class LoftSerializer(serializers.ModelSerializer):
    rollCount = serializers.SerializerMethodField()

    class Meta:
        model = Loft
        fields = ("id", "name", "location", "notes", "rollCount", "created_at")
        read_only_fields = ("id", "rollCount", "created_at")

    def get_rollCount(self, obj):
        if hasattr(obj, "roll_count"):
            return obj.roll_count
        return obj.rolls.count()


class ClothRollSerializer(serializers.ModelSerializer):
    loftId = serializers.PrimaryKeyRelatedField(source="loft", queryset=Loft.objects.all())
    rollCode = serializers.CharField(source="roll_code")
    fabricWeightGsm = serializers.IntegerField(source="fabric_weight_gsm", required=False)
    coolDownFull = serializers.BooleanField(source="cool_down_full", required=False)
    loftName = serializers.CharField(source="loft.name", read_only=True)

    class Meta:
        model = ClothRoll
        fields = (
            "id",
            "loftId",
            "loftName",
            "rollCode",
            "status",
            "coolDownFull",
            "fabricWeightGsm",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "loftName", "created_at", "updated_at")

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # 「冷却已满」只能由管理员勾选；操作工只读。
        if "cool_down_full" in attrs and user is not None:
            if user.role != User.ROLE_ADMIN:
                raise PermissionDenied("仅管理员可在布卷专页勾选「冷却已满」")
            if (
                attrs["cool_down_full"]
                and attrs.get("status", getattr(self.instance, "status", None))
                != ClothRoll.STATUS_DIPPING
            ):
                raise serializers.ValidationError(
                    {"coolDownFull": "仅浸渍中的布卷需要确认冷却已满"}
                )

        loft = attrs.get("loft") or getattr(self.instance, "loft", None)
        roll_code = attrs.get("roll_code") or getattr(self.instance, "roll_code", None)
        if loft and roll_code:
            qs = ClothRoll.objects.filter(loft=loft, roll_code=roll_code)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"rollCode": "同一帆布间卷号必须唯一"})

        new_status = attrs.get("status")
        if new_status is not None and self.instance is not None:
            if new_status == ClothRoll.STATUS_CURED:
                # 标已固化只看最近浸渍固化时长，不看冷却勾选。
                ok, msg = can_mark_roll_cured(self.instance)
                if not ok:
                    raise serializers.ValidationError({"status": msg})
            # 浸渍中 -> 原布的冷却闸门不在这里按可能陈旧的快照判断，
            # 统一交给 views.perform_update 中基于数据库当前状态的条件 UPDATE。
        elif new_status == ClothRoll.STATUS_CURED:
            raise serializers.ValidationError({"status": "新建布卷不能直接设为已固化"})
        return attrs


class DipRunSerializer(serializers.ModelSerializer):
    rollId = serializers.PrimaryKeyRelatedField(
        source="roll", queryset=ClothRoll.objects.all()
    )
    startedAt = serializers.DateTimeField(source="started_at")
    resinPct = serializers.DecimalField(source="resin_pct", max_digits=5, decimal_places=2)
    cureHours = serializers.DecimalField(
        source="cure_hours",
        max_digits=6,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    rollCode = serializers.CharField(source="roll.roll_code", read_only=True)
    loftName = serializers.CharField(source="roll.loft.name", read_only=True)

    class Meta:
        model = DipRun
        fields = (
            "id",
            "rollId",
            "rollCode",
            "loftName",
            "startedAt",
            "resinPct",
            "cureHours",
            "notes",
            "created_at",
        )
        read_only_fields = ("id", "rollCode", "loftName", "created_at")
