from django.db import transaction
from django.db.models import Count
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from accounts.models import User

from . import rules
from .models import ClothRoll, DipRun, Loft
from .serializers import ClothRollSerializer, DipRunSerializer, LoftSerializer


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "该卷状态刚被他人更新，请刷新架面后重试"
    default_code = "roll_state_conflict"


class LoftViewSet(viewsets.ModelViewSet):
    queryset = Loft.objects.annotate(roll_count=Count("rolls")).all()
    serializer_class = LoftSerializer


class ClothRollViewSet(viewsets.ModelViewSet):
    serializer_class = ClothRollSerializer

    def get_queryset(self):
        qs = ClothRoll.objects.select_related("loft").all()
        loft_id = self.request.query_params.get("loftId")
        status = self.request.query_params.get("status")
        if loft_id:
            qs = qs.filter(loft_id=loft_id)
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_update(self, serializer):
        # 以「请求快照」与「数据库当前状态」共同判断，避免并发败者读到胜者
        # 提交后的 raw 后把拨回当成无操作 raw→raw 返回 200。
        instance = serializer.instance
        new_status = serializer.validated_data.get("status")
        current = (
            ClothRoll.objects.filter(pk=instance.pk)
            .values_list("status", "cool_down_full")
            .first()
        )
        wants_revert = new_status == ClothRoll.STATUS_RAW and (
            instance.status == ClothRoll.STATUS_DIPPING
            or (current and current[0] == ClothRoll.STATUS_DIPPING)
        )
        if wants_revert:
            # 浸渍中 -> 原布必须走带冷却闸门的条件 UPDATE，保证并发只许一笔成功。
            try:
                rules.revert_dipping_to_raw(instance.pk)
            except ValueError as exc:
                raise ValidationError({"status": [str(exc)]})
            except rules.RollStateConflict as exc:
                raise Conflict(str(exc))
            # 条件更新已把状态/勾写写库；随后 serializer.save() 是全字段保存，
            # 必须先刷新内存实例，否则会把冷却勾选的旧值写回去。
            serializer.instance.refresh_from_db()
            # 同一请求里携带的 coolDownFull 也不得再覆盖拨回结果。
            serializer.validated_data.pop("cool_down_full", None)
        elif (
            new_status == ClothRoll.STATUS_DIPPING
            and instance.status != ClothRoll.STATUS_DIPPING
        ):
            # 重新进入浸渍中即开启新一轮冷却，旧勾选不得沿用。
            serializer.validated_data["cool_down_full"] = False
        serializer.save()

    @action(detail=True, methods=["post"], url_path="set_cool_down")
    def set_cool_down(self, request, pk=None):
        """布卷专页「冷却已满」勾选：仅管理员可写，操作工只读。"""
        roll = self.get_object()
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied("仅管理员可勾选「冷却已满」")
        full = bool(request.data.get("full", True))
        if full and roll.status != ClothRoll.STATUS_DIPPING:
            raise ValidationError({"full": "仅浸渍中的布卷可勾选冷却已满"})
        roll.cool_down_full = full
        roll.save(update_fields=["cool_down_full", "updated_at"])
        return Response(ClothRollSerializer(roll, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="revert_to_raw")
    def revert_to_raw(self, request, pk=None):
        """
        布卷专页「拨回原布」动作。以条件 UPDATE 为唯一事实来源：
        冷却未满 -> 400；卷已被他人先行拨回/改态 -> 409（并发只许一笔成功）。
        """
        roll = self.get_object()
        if roll.status != ClothRoll.STATUS_DIPPING:
            # 快照已非浸渍中：本动作没有可执行的拨回。
            raise Conflict("该卷已不是浸渍中状态，请刷新架面")
        try:
            roll = rules.revert_dipping_to_raw(roll.pk)
        except ValueError as exc:
            raise ValidationError({"status": [str(exc)]})
        except rules.RollStateConflict as exc:
            raise Conflict(str(exc))
        return Response(ClothRollSerializer(roll, context={"request": request}).data)


class DipRunViewSet(viewsets.ModelViewSet):
    serializer_class = DipRunSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = DipRun.objects.select_related("roll", "roll__loft").all()
        roll_id = self.request.query_params.get("rollId")
        if roll_id:
            qs = qs.filter(roll_id=roll_id)
        return qs

    def perform_create(self, serializer):
        # 冷却是否已满不拦浸渍登记；新浸渍开启新一轮冷却，重置勾选；
        # 原布登记浸渍后自动转为浸渍中。已固化卷状态不动（固化不看此勾）。
        roll = serializer.validated_data["roll"]
        with transaction.atomic():
            serializer.save()
            ClothRoll.objects.filter(pk=roll.pk).exclude(
                status=ClothRoll.STATUS_CURED
            ).update(status=ClothRoll.STATUS_DIPPING, cool_down_full=False)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    data = {
        "loftCount": Loft.objects.count(),
        "rawRollCount": ClothRoll.objects.filter(status=ClothRoll.STATUS_RAW).count(),
        "dippingRollCount": ClothRoll.objects.filter(
            status=ClothRoll.STATUS_DIPPING
        ).count(),
        "curedRollCount": ClothRoll.objects.filter(status=ClothRoll.STATUS_CURED).count(),
        "dipRunCount": DipRun.objects.count(),
    }
    return Response(data)
