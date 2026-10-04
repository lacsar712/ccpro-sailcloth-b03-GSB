import threading
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import ClothRoll, DipRun, Loft

User = get_user_model()


def make_user(username, role):
    return User.objects.create_user(username=username, password="pw123456", role=role)


def authed_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class CoolingRuleTests(TestCase):
    """浸渍中拨回原布受「冷却已满」约束；仅管理员可勾；已固化不看这勾。"""

    def setUp(self):
        self.admin = make_user("admin", "admin")
        self.worker = make_user("worker", "worker")
        self.loft = Loft.objects.create(name="北岸帆布间")
        self.roll = ClothRoll.objects.create(
            loft=self.loft, roll_code="R-1", status=ClothRoll.STATUS_DIPPING
        )

    def test_move_back_blocked_until_cooling_checked(self):
        worker = authed_client(self.worker)

        # 未勾冷却已满：拨回必须失败
        resp = worker.patch(f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.roll.refresh_from_db()
        self.assertEqual(self.roll.status, ClothRoll.STATUS_DIPPING)

        # 操作工不能勾选冷却已满
        resp = worker.patch(
            f"/api/rolls/{self.roll.id}/", {"coolingDone": True}, format="json"
        )
        self.assertEqual(resp.status_code, 403)
        self.roll.refresh_from_db()
        self.assertFalse(self.roll.cooling_done)

        # 管理员勾成已满
        admin = authed_client(self.admin)
        resp = admin.patch(
            f"/api/rolls/{self.roll.id}/", {"coolingDone": True}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.roll.refresh_from_db()
        self.assertTrue(self.roll.cooling_done)

        # 勾成已满后可以拨回
        resp = worker.patch(f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.roll.refresh_from_db()
        self.assertEqual(self.roll.status, ClothRoll.STATUS_RAW)

    def test_cured_roll_ignores_cooling_flag(self):
        roll = ClothRoll.objects.create(
            loft=self.loft, roll_code="R-2", status=ClothRoll.STATUS_CURED
        )
        DipRun.objects.create(
            roll=roll,
            started_at=timezone.now(),
            resin_pct=Decimal("28.00"),
            cure_hours=Decimal("13.00"),
        )
        worker = authed_client(self.worker)
        # 已固化拨回原布不看冷却勾
        resp = worker.patch(f"/api/rolls/{roll.id}/", {"status": "raw"}, format="json")
        self.assertEqual(resp.status_code, 200)
        roll.refresh_from_db()
        self.assertEqual(roll.status, ClothRoll.STATUS_RAW)

    def test_cooling_does_not_block_dip_registration(self):
        worker = authed_client(self.worker)
        resp = worker.post(
            "/api/dips/",
            {
                "rollId": self.roll.id,
                "startedAt": timezone.now().isoformat(),
                "resinPct": "28.50",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_reentering_dipping_resets_cooling_flag(self):
        self.roll.cooling_done = True
        self.roll.status = ClothRoll.STATUS_RAW
        self.roll.save()
        worker = authed_client(self.worker)
        resp = worker.patch(
            f"/api/rolls/{self.roll.id}/", {"status": "dipping"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.roll.refresh_from_db()
        self.assertFalse(self.roll.cooling_done)

    def test_cured_rule_still_enforced(self):
        worker = authed_client(self.worker)
        resp = worker.patch(
            f"/api/rolls/{self.roll.id}/", {"status": "cured"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_second_move_back_rejected(self):
        self.roll.cooling_done = True
        self.roll.save()
        worker = authed_client(self.worker)
        resp = worker.patch(f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json")
        self.assertEqual(resp.status_code, 200)
        # 同一卷再拨一次：只许一笔成功
        resp = worker.patch(f"/api/rolls/{self.roll.id}/", {"status": "raw"}, format="json")
        self.assertEqual(resp.status_code, 409)

    def test_ledger_edit_of_raw_roll_still_works(self):
        raw = ClothRoll.objects.create(
            loft=self.loft, roll_code="R-3", status=ClothRoll.STATUS_RAW
        )
        worker = authed_client(self.worker)
        resp = worker.patch(
            f"/api/rolls/{raw.id}/",
            {
                "loftId": self.loft.id,
                "rollCode": "R-3",
                "status": "raw",
                "fabricWeightGsm": 400,
                "notes": "台账改克重",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        raw.refresh_from_db()
        self.assertEqual(raw.fabric_weight_gsm, 400)


@override_settings()
class ConcurrentMoveBackTests(TransactionTestCase):
    """勾成已满后，两人交叉把同一卷拨回原布：只许一笔成功。"""

    def test_only_one_move_back_succeeds(self):
        if connections["default"].vendor == "sqlite" and ":memory:" in connections[
            "default"
        ].settings_dict.get("NAME", ""):
            self.skipTest("内存 SQLite 不支持跨连接并发，跳过")

        admin = make_user("admin", "admin")
        loft = Loft.objects.create(name="北岸帆布间")
        roll = ClothRoll.objects.create(
            loft=loft,
            roll_code="R-9",
            status=ClothRoll.STATUS_DIPPING,
            cooling_done=True,
        )

        results = []

        def move_back(username):
            client = APIClient()
            user = User.objects.create_user(
                username=username, password="pw123456", role="worker"
            )
            client.force_authenticate(user)
            try:
                resp = client.patch(
                    f"/api/rolls/{roll.id}/", {"status": "raw"}, format="json"
                )
                results.append(resp.status_code)
            finally:
                connections.close_all()

        t1 = threading.Thread(target=move_back, args=("w1",))
        t2 = threading.Thread(target=move_back, args=("w2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(sorted(results), [200, 409])
        roll.refresh_from_db()
        self.assertEqual(roll.status, ClothRoll.STATUS_RAW)
