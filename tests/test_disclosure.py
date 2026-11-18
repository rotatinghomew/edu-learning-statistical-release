import unittest
from fractions import Fraction
from pathlib import Path

from learning_statistical_release.disclosure import (MIN_PUBLISHABLE_COUNT,
                                                     LinearBasis,
                                                     evaluate_marginals)
from learning_statistical_release.metrics import Marginal
from learning_statistical_release.records import read_learner_records
from learning_statistical_release.service import (STATUS_FULL, STATUS_PARTIAL,
                                                  STATUS_REFUSED, Actor,
                                                  ReleaseService)

DATA = Path(__file__).parent.parent / "data" / "learners.csv"
S1 = "2026-S1"


def south_scope():
    return Actor("城南街道负责人", "recipient", scope="street:城南街道")


def make_service():
    return ReleaseService(read_learner_records(DATA))


def rows_by_key(delivery):
    return {row.key: row for row in delivery.rows}


class LinearBasisTests(unittest.TestCase):
    def test_determines_only_span_members(self):
        basis = LinearBasis()
        basis.add({("n", "a"): Fraction(1), ("n", "b"): Fraction(1)})
        self.assertTrue(basis.determines({("n", "a"): Fraction(2), ("n", "b"): Fraction(2)}))
        self.assertFalse(basis.determines({("n", "a"): Fraction(1)}))
        basis.add({("n", "a"): Fraction(1), ("n", "c"): Fraction(1)})
        self.assertTrue(basis.determines({("n", "b"): Fraction(1), ("n", "c"): Fraction(-1)}))
        self.assertFalse(basis.determines({("n", "d"): Fraction(1)}))

    def test_dependent_vector_does_not_extend_basis(self):
        basis = LinearBasis()
        self.assertTrue(basis.add({("n", "a"): Fraction(1)}))
        self.assertFalse(basis.add({("n", "a"): Fraction(3)}))


class EngineTests(unittest.TestCase):
    def test_small_distinct_count_is_suppressed(self):
        marginal = Marginal(key=("某组",),
                            cells=frozenset({(S1, "甲街道", "书法班"),
                                             (S1, "甲街道", "合唱团")}),
                            headcount=5, distinct_learners=2,
                            attendance_sum=Fraction(3))
        decisions, _, new_protected = evaluate_marginals([marginal], [], [])
        self.assertFalse(decisions[0].released)
        self.assertIn("去重学员数", decisions[0].reason)
        self.assertTrue(new_protected)


class CrossQueryTests(unittest.TestCase):
    def test_small_cell_suppressed_never_zero(self):
        service = make_service()
        delivery = service.query(south_scope(), ["course"],
                                 {"period": S1, "street": "城南街道"},
                                 include_total=True, label="分课程")
        rows = rows_by_key(delivery)
        taiji = rows[("太极班",)]
        self.assertEqual(taiji.status, "不予公开")
        self.assertIsNone(taiji.headcount)
        self.assertIsNone(taiji.mean_attendance)
        self.assertNotEqual(taiji.headcount, 0)
        self.assertIn("最小可公开人数", taiji.reason)

    def test_total_withheld_when_cells_would_reveal_small_cell(self):
        service = make_service()
        delivery = service.query(south_scope(), ["course"],
                                 {"period": S1, "street": "城南街道"},
                                 include_total=True, label="分课程")
        self.assertEqual(delivery.status, STATUS_PARTIAL)
        rows = rows_by_key(delivery)
        self.assertEqual(rows[("书法班",)].headcount, 8)
        self.assertEqual(rows[("合唱团",)].headcount, 7)
        self.assertEqual(rows[("合计",)].status, "不予公开")
        self.assertIn("反推", rows[("合计",)].reason)

    def test_later_total_request_is_refused(self):
        service = make_service()
        actor = south_scope()
        first = service.query(actor, ["course"], {"period": S1, "street": "城南街道"},
                              label="分课程")
        self.assertEqual(first.status, STATUS_PARTIAL)
        second = service.query(actor, [], {"period": S1, "street": "城南街道"},
                               label="只要合计")
        self.assertEqual(second.status, STATUS_REFUSED)
        self.assertTrue(second.reasons)
        self.assertEqual(second.rows[0].status, "不予公开")

    def test_regional_total_and_breakdown_cannot_be_combined(self):
        """地区合计与分地区表相减可得到小单元：引擎应阻断补全差减链的请求。"""
        service = make_service()
        actor = south_scope()
        service.query(actor, ["course"], {"period": S1, "street": "城南街道"},
                      label="城南分课程")
        regional = service.query(actor, ["course"], {"period": S1}, label="全区分课程")
        self.assertEqual(regional.status, STATUS_FULL)
        east = service.query(actor, ["course"], {"period": S1, "street": "城东街道"},
                             label="城东分课程")
        east_rows = rows_by_key(east)
        # 全区书法合计 - 城南书法 - 城东书法 = 城西书法（受保护），故城东书法不可再给
        self.assertEqual(east_rows[("书法班",)].status, "不予公开")
        self.assertIn("反推", east_rows[("书法班",)].reason)
        west = service.query(actor, ["course"], {"period": S1, "street": "城西街道"},
                             label="城西分课程")
        west_rows = rows_by_key(west)
        self.assertEqual(west_rows[("书法班",)].status, "不予公开")  # 本身低于下限
        # 全区太极合计 - 城东太极 - 城西太极 = 城南太极（受保护）
        self.assertEqual(west_rows[("太极班",)].status, "不予公开")
        self.assertIn("反推", west_rows[("太极班",)].reason)
        self.assertEqual(west_rows[("合唱团",)].status, "公开")
        # 受保护单元从未出现在任何交付中
        for delivery in service.deliveries(actor):
            for row in delivery.rows:
                if row.status == "公开":
                    self.assertGreaterEqual(row.headcount, MIN_PUBLISHABLE_COUNT)

    def test_released_values_stay_stable(self):
        service = make_service()
        actor = south_scope()
        first = service.query(actor, ["course"], {"period": S1, "street": "城南街道"},
                              label="分课程")
        service.query(actor, ["course"], {"period": S1}, label="全区分课程")
        again = service.query(actor, ["course"], {"period": S1, "street": "城南街道"},
                              label="分课程（再次）")
        first_rows = rows_by_key(first)
        for row in again.rows:
            if row.key in first_rows and first_rows[row.key].status == "公开":
                self.assertEqual(row.status, "公开")
                self.assertEqual(row.headcount, first_rows[row.key].headcount)
                self.assertAlmostEqual(row.mean_attendance,
                                       first_rows[row.key].mean_attendance)
        # 已发出的交付记录不被回写
        history = service.deliveries(actor)
        self.assertEqual(history[0], first)

    def test_no_matching_records_is_refused(self):
        service = make_service()
        delivery = service.query(south_scope(), ["course"],
                                 {"period": "2099-S9", "street": "城南街道"})
        self.assertEqual(delivery.status, STATUS_REFUSED)
        self.assertIn("没有匹配的记录", delivery.reasons)


if __name__ == "__main__":
    unittest.main()
