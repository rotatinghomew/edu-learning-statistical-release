import unittest
from pathlib import Path

from learning_statistical_release.records import read_learner_records
from learning_statistical_release.service import (STATUS_FULL, STATUS_PARTIAL,
                                                  STATUS_REFUSED, Actor,
                                                  ReleaseService)

DATA = Path(__file__).parent.parent / "data" / "learners.csv"
S1 = "2026-S1"


def make_service():
    return ReleaseService(read_learner_records(DATA))


def rows_by_key(delivery):
    return {row.key: row for row in delivery.rows}


class SubscriptionTests(unittest.TestCase):
    def test_subscription_rechecked_at_delivery_time(self):
        service = make_service()
        calligraphy = Actor("书法班负责人", "recipient", scope="course:书法班")
        _, preview = service.subscribe(calligraphy, ["street"],
                                       {"period": S1, "course": "书法班"},
                                       label="书法班分街道统计")
        preview_rows = rows_by_key(preview)
        # 预览时：城南书法 8 人可以公开，城西书法 2 人低于下限
        self.assertEqual(preview_rows[("城南街道",)].status, "公开")
        self.assertEqual(preview_rows[("城西街道",)].status, "不予公开")
        # 预览后、交付前，同一接收范围先拿到了书法班合计
        total = service.query(calligraphy, [], {"period": S1, "course": "书法班"},
                              label="书法班合计")
        self.assertEqual(total.status, STATUS_FULL)
        # 订阅运行时重新判断：合计 + 城东 + 城南 会反推出城西的 2 人
        deliveries = service.run_subscriptions()
        self.assertEqual(len(deliveries), 1)
        delivery_rows = rows_by_key(deliveries[0])
        self.assertEqual(delivery_rows[("城东街道",)].status, "公开")
        self.assertEqual(delivery_rows[("城南街道",)].status, "不予公开")
        self.assertIn("反推", delivery_rows[("城南街道",)].reason)
        self.assertEqual(delivery_rows[("城西街道",)].status, "不予公开")
        # 已发出的合计不被回写
        history = service.deliveries(calligraphy)
        totals = [d for d in history if d.label == "书法班合计"]
        self.assertEqual(totals[0].rows[0].headcount, 16)

    def test_subscription_delivery_records_are_kept(self):
        service = make_service()
        actor = Actor("太极班负责人", "recipient", scope="course:太极班")
        service.subscribe(actor, ["street"], {"period": S1, "course": "太极班"},
                          label="太极班分街道统计")
        service.run_subscriptions()
        history = service.deliveries(actor)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].scope, "course:太极班")
        self.assertEqual(history[0].data_version, service.data_version)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()
        self.staff = Actor("运营专员", "staff")
        self.south = Actor("城南街道负责人", "recipient", scope="street:城南街道")
        self.calligraphy = Actor("书法班负责人", "recipient", scope="course:书法班")
        self.service.query(self.south, ["course"], {"period": S1, "street": "城南街道"},
                           include_total=True, label="城南分课程")
        self.service.query(self.calligraphy, [], {"period": S1, "course": "书法班"},
                           label="书法班合计")

    def test_staff_sees_exact_internal_stats(self):
        marginals = self.service.internal_stats(
            self.staff, ["course"], {"period": S1, "street": "城西街道"})
        by_course = {m.key[0]: m for m in marginals}
        self.assertEqual(by_course["书法班"].headcount, 2)
        self.assertEqual(by_course["书法班"].distinct_learners, 2)

    def test_recipient_cannot_see_internal_stats(self):
        with self.assertRaises(PermissionError):
            self.service.internal_stats(self.south, ["course"])

    def test_staff_sees_all_deliveries_with_reasons(self):
        deliveries = self.service.deliveries(self.staff)
        self.assertEqual(len(deliveries), 2)
        south_delivery = deliveries[0]
        self.assertEqual(south_delivery.status, STATUS_PARTIAL)
        self.assertTrue(south_delivery.reasons)
        suppressed = [row for row in south_delivery.rows if row.status == "不予公开"]
        self.assertTrue(all(row.reason for row in suppressed))

    def test_recipient_sees_only_own_deliveries(self):
        own = self.service.deliveries(self.south)
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0].scope, "street:城南街道")
        with self.assertRaises(PermissionError):
            self.service.deliveries(self.south, scope="course:书法班")

    def test_recipient_cannot_query_under_other_scope(self):
        with self.assertRaises(PermissionError):
            self.service.query(self.south, ["course"], {"period": S1},
                               scope="course:书法班")

    def test_staff_query_on_behalf_uses_named_scope(self):
        delivery = self.service.query(self.staff, [],
                                      {"period": S1, "street": "城南街道"},
                                      scope="street:城南街道", label="代查合计")
        # 城南范围此前已拿到分课程人数，合计会反推太极班，故被拒绝
        self.assertEqual(delivery.status, STATUS_REFUSED)
        self.assertEqual(delivery.scope, "street:城南街道")

    def test_staff_query_requires_scope(self):
        with self.assertRaises(ValueError):
            self.service.query(self.staff, ["course"], {"period": S1})

    def test_actor_validation(self):
        with self.assertRaises(ValueError):
            Actor("某人", "unknown")
        with self.assertRaises(ValueError):
            Actor("某人", "recipient")


if __name__ == "__main__":
    unittest.main()
