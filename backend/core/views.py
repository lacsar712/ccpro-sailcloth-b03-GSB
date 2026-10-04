from django.db.models import Count
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ClothRoll, DipRun, Loft
from .serializers import ClothRollSerializer, DipRunSerializer, LoftSerializer


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

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        new_status = validated.get("status")

        if new_status == ClothRoll.STATUS_RAW:
            if instance.status == ClothRoll.STATUS_RAW and set(validated) <= {"status"}:
                # 纯拨回请求重复提交：拨回是一次性跃迁，只许一笔成功
                return Response(
                    {"detail": "该卷已是原布，拨回仅一笔生效"},
                    status=drf_status.HTTP_409_CONFLICT,
                )
            if instance.status in (ClothRoll.STATUS_DIPPING, ClothRoll.STATUS_CURED):
                # 拨回原布走原子条件更新。两人交叉拨同一卷时，
                # 只有抢到行的一笔生效，另一笔 409，绝不双成功。
                write = dict(validated)
                write["updated_at"] = timezone.now()
                condition = {"pk": instance.pk, "status": instance.status}
                if instance.status == ClothRoll.STATUS_DIPPING:
                    condition["cooling_done"] = True
                updated = ClothRoll.objects.filter(**condition).update(**write)
                if not updated:
                    return Response(
                        {"detail": "拨回失败：该卷已被他人变更，请刷新后重试"},
                        status=drf_status.HTTP_409_CONFLICT,
                    )
                instance.refresh_from_db()
                return Response(self.get_serializer(instance).data)

        if (
            new_status == ClothRoll.STATUS_DIPPING
            and instance.status != ClothRoll.STATUS_DIPPING
        ):
            # 重新入浸：冷却重新计时，「冷却已满」勾选清零
            serializer.save(cooling_done=False)
        else:
            serializer.save()
        return Response(serializer.data)


class DipRunViewSet(viewsets.ModelViewSet):
    serializer_class = DipRunSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = DipRun.objects.select_related("roll", "roll__loft").all()
        roll_id = self.request.query_params.get("rollId")
        if roll_id:
            qs = qs.filter(roll_id=roll_id)
        return qs


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
