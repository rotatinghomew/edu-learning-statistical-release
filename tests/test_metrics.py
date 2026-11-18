import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from learning_statistical_release.metrics import aggregate
from learning_statistical_release.records import read_learner_records

DATA = Path(__file__).parent.parent / "data" / "learners.csv"
SOUTH_S1 = {"period": "2026-S1", "street": "城南街道"}


class MetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = read_learner_records(DATA)

    def test_headcount_counts_enrollments(self):
        marginals = aggregate(self.records, ["course"], SOUTH_S1)
        by_course = {marginal.key[0]: marginal for marginal in marginals}
        self.assertEqual(by_course["书法班"].headcount, 8)
        self.assertEqual(by_course["合唱团"].headcount, 7)
        self.assertEqual(by_course["太极班"].headcount, 2)

    def test_distinct_learners_not_additive_across_courses(self):
        marginals = aggregate(self.records, ["course"], SOUTH_S1, include_total=True)
        total = next(m for m in marginals if m.key == ("合计",))
        per_course = [m for m in marginals if m.key != ("合计",)]
        self.assertEqual(total.headcount, 17)
        self.assertEqual(total.distinct_learners, 14)
        self.assertLess(total.distinct_learners,
                        sum(m.distinct_learners for m in per_course))

    def test_mean_attendance_is_not_a_count(self):
        marginals = aggregate(self.records, ["course"], SOUTH_S1, include_total=True)
        total = next(m for m in marginals if m.key == ("合计",))
        per_course = [m for m in marginals if m.key != ("合计",)]
        self.assertAlmostEqual(total.mean_attendance,
                               float(total.attendance_sum) / total.headcount)
        self.assertNotAlmostEqual(total.mean_attendance,
                                  sum(m.mean_attendance for m in per_course))
        # 可相加的是出勤总和与人数，均值本身不可相加
        self.assertEqual(total.attendance_sum,
                         sum((m.attendance_sum for m in per_course), Fraction(0)))
        self.assertEqual(total.headcount, sum(m.headcount for m in per_course))

    def test_unknown_dimension_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知维度"):
            aggregate(self.records, ["region"])
        with self.assertRaisesRegex(ValueError, "未知维度"):
            aggregate(self.records, ["course"], {"region": "某处"})


class LearnerRecordTests(unittest.TestCase):
    def test_missing_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("period,street,course,learner_id\n2026-S1,某街道,某课程,L001\n",
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "attendance"):
                read_learner_records(path)

    def test_attendance_out_of_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("period,street,course,learner_id,attendance\n"
                            "2026-S1,某街道,某课程,L001,1.5\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "范围"):
                read_learner_records(path)


if __name__ == "__main__":
    unittest.main()
