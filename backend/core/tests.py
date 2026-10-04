import threading
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITransactionTestCase, APITestCase

from accounts.models import User
from core.models import ClothRoll, DipRun, Loft
from core.rules import revert_dipping_to_raw


def make_users():
    admin = User.objects.create_user(
        username="admin", password="x", role=User.ROLE_ADMIN,
        is_staff=True, is_superuser=True,
    )
    worker = User.objects.create_user(
        username="worker", password="x", role=User.ROLE_WORKER
    )
    return admin, worker


def client_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class CoolDownGateTests(APITestCase):
    def setUp(self):
        self.admin, self.worker = make_users()
        self.loft = Loft.objects.create(name="北岸帆布间", location="港区二号库")
        self.roll = ClothRoll.objects.create(
            loft=self.loft, roll_code="R-01", status=ClothRoll.STATUS_DIPPING
        )
        DipRun.objects.create(
            roll=self.roll,
            started_at=timezone.now() - timedelta(hours=6),
            resin_pct=Decimal("28.00"),
            cure_hours=None,
        )

    # 未勾冷却已满：拨回原布必须失败，卷仍是浸渍中。
    def test_revert_blocked_when_not_full(self):
        resp = client_for(self.worker).patch(
            f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("冷却", resp.data["status"][0])
        self.roll.refresh_from_db()
        self.assertEqual(self.roll.status, ClothRoll.STATUS_DIPPING)
        self.assertFalse(self.roll.cool_down_full)

    # 操作工不能勾选冷却已满：专页只读。
    def test_worker_cannot_check_cool_down(self):
        resp = client_for(self.worker).post(
            f"/api/rolls/{self.roll.id}/set_cool_down/", {"full": True}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        # 直接 PATCH 卷字段同样拒绝。
        resp2 = client_for(self.worker).patch(
            f"/api/rolls/{self.roll.id}/", {"coolDownFull": True}, format="json"
        )
        self.assertEqual(resp2.status_code, status.HTTP_403_FORBIDDEN)
        self.roll.refresh_from_db()
        self.assertFalse(self.roll.cool_down_full)

    # 管理员勾成已满后可以拨回，拨回后勾选被清掉（新一轮冷却）。
    def test_admin_check_then_revert_succeeds(self):
        c = client_for(self.admin)
        resp = c.post(
            f"/api/rolls/{self.roll.id}/set_cool_down/", {"full": True}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["coolDownFull"])

        resp = c.patch(
            f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.roll.refresh_from_db()
        self.assertEqual(self.roll.status, ClothRoll.STATUS_RAW)
        self.assertFalse(self.roll.cool_down_full)

    # 冷却勾选只能对浸渍中卷操作。
    def test_check_only_allowed_for_dipping(self):
        raw_roll = ClothRoll.objects.create(
            loft=self.loft, roll_code="R-02", status=ClothRoll.STATUS_RAW
        )
        resp = client_for(self.admin).post(
            f"/api/rolls/{raw_roll.id}/set_cool_down/", {"full": True}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(ClothRoll.objects.get(pk=raw_roll.id).cool_down_full)

    # 取消勾选后拨回应再次被拒。
    def test_uncheck_blocks_revert_again(self):
        c = client_for(self.admin)
        c.post(
            f"/api/rolls/{self.roll.id}/set_cool_down/", {"full": True}, format="json"
        )
        c.post(
            f"/api/rolls/{self.roll.id}/set_cool_down/", {"full": False}, format="json"
        )
        resp = c.patch(
            f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ClothRoll.objects.get(pk=self.roll.id).status,
                         ClothRoll.STATUS_DIPPING)

    # 已固化不看这勾：固化时长达标即可标已固化；已固化拨原布也不经冷却闸门。
    def test_cured_ignores_cool_down_flag(self):
        self.roll.dip_runs.update(cure_hours=Decimal("14.00"))
        resp = client_for(self.worker).patch(
            f"/api/rolls/{self.roll.id}/", {"status": "cured"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(ClothRoll.objects.get(pk=self.roll.id).cool_down_full)

        resp = client_for(self.worker).patch(
            f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(ClothRoll.objects.get(pk=self.roll.id).status,
                         ClothRoll.STATUS_RAW)

    # 冷却不拦登记浸渍；登记后重置勾选；原布登记浸渍自动转浸渍中。
    def test_dip_registration_resets_flag(self):
        c = client_for(self.worker)
        client_for(self.admin).post(
            f"/api/rolls/{self.roll.id}/set_cool_down/", {"full": True}, format="json"
        )
        resp = c.post(
            "/api/dips/",
            {
                "rollId": self.roll.id,
                "startedAt": timezone.now().isoformat(),
                "resinPct": "29.00",
                "cureHours": None,
                "notes": "再次浸渍",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.roll.refresh_from_db()
        self.assertEqual(self.roll.status, ClothRoll.STATUS_DIPPING)
        self.assertFalse(self.roll.cool_down_full)

        raw_roll = ClothRoll.objects.create(
            loft=self.loft, roll_code="R-09", status=ClothRoll.STATUS_RAW
        )
        resp = client_for(self.worker).post(
            "/api/dips/",
            {
                "rollId": raw_roll.id,
                "startedAt": timezone.now().isoformat(),
                "resinPct": "27.00",
                "cureHours": None,
                "notes": "",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ClothRoll.objects.get(pk=raw_roll.id).status,
                         ClothRoll.STATUS_DIPPING)

    # 固化时长不足仍不可标已固化（既有规则不回归）。
    def test_short_cure_still_blocks_cured(self):
        self.roll.dip_runs.update(cure_hours=Decimal("4.00"))
        resp = client_for(self.admin).patch(
            f"/api/rolls/{self.roll.id}/", {"status": "cured"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # 拨回原布后再手动标回浸渍中：冷却勾选必须重置，不能沿用旧确认。
    def test_reentering_dipping_resets_flag(self):
        c = client_for(self.admin)
        c.post(
            f"/api/rolls/{self.roll.id}/set_cool_down/", {"full": True}, format="json"
        )
        c.post(f"/api/rolls/{self.roll.id}/revert_to_raw/", {}, format="json")
        resp = c.patch(
            f"/api/rolls/{self.roll.id}/", {"status": "dipping"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(ClothRoll.objects.get(pk=self.roll.id).cool_down_full)


class ConcurrentRevertTests(APITransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.admin, _ = make_users()
        self.loft = Loft.objects.create(name="并发帆布间")
        self.roll = ClothRoll.objects.create(
            loft=self.loft, roll_code="C-01",
            status=ClothRoll.STATUS_DIPPING, cool_down_full=True,
        )

    def _cross_call(self, outcomes, use_action):
        # 两个线程（同一管理员）同时把同一卷拨回原布，只许一笔成功。
        c = client_for(User.objects.get(username="admin"))
        try:
            if use_action:
                resp = c.post(
                    f"/api/rolls/{self.roll.id}/revert_to_raw/", {}, format="json"
                )
            else:
                resp = c.patch(
                    f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json"
                )
            outcomes.append(resp.status_code)
        finally:
            c.force_authenticate(user=None)
            connection.close()

    def _run_pair(self, use_action):
        outcomes = []
        barrier = threading.Barrier(2)

        def go():
            barrier.wait()
            self._cross_call(outcomes, use_action)

        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        return outcomes

    def test_two_cross_reverts_only_one_wins_action(self):
        outcomes = self._run_pair(use_action=True)
        self.assertEqual(sorted(outcomes), [200, 409])
        roll = ClothRoll.objects.get(pk=self.roll.id)
        self.assertEqual(roll.status, ClothRoll.STATUS_RAW)
        self.assertFalse(roll.cool_down_full)

    def test_two_cross_reverts_only_one_wins_patch(self):
        outcomes = self._run_pair(use_action=False)
        self.assertEqual(sorted(outcomes), [200, 409])
        self.assertEqual(
            ClothRoll.objects.get(pk=self.roll.id).status, ClothRoll.STATUS_RAW
        )

    def test_rule_helper_reverts_then_conflicts(self):
        roll = revert_dipping_to_raw(self.roll.id)
        self.assertEqual(roll.status, ClothRoll.STATUS_RAW)
        with self.assertRaises(ClothRoll.DoesNotExist):
            revert_dipping_to_raw(999999)
