"""统计口径：人数、去重学员数、平均出勤率各自独立定义。

- 人数：报名记录条数。一名学员选多门课程会重复计入各课程人数。
- 去重学员数：按 learner_id 去重。跨课程不可相加（同一人可出现在多门
  课程中），跨课程合计必须回到记录重新去重。
- 平均出勤率：报名记录出勤率的均值。均值不是计数，不能相加；只有
  出勤总和与人数一样是可加的。
"""
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

DIMENSIONS = ("period", "street", "course")
TOTAL_KEY = ("合计",)


@dataclass(frozen=True)
class Marginal:
    """一个分组（边际）的精确统计；cells 为它覆盖的基础单元。"""

    key: tuple
    cells: frozenset
    headcount: int
    distinct_learners: int
    attendance_sum: Fraction

    @property
    def mean_attendance(self):
        if not self.headcount:
            return None
        return float(self.attendance_sum) / self.headcount


def cell_of(record):
    return (record["period"], record["street"], record["course"])


def base_cells(records):
    return sorted({cell_of(record) for record in records})


def _check_dimensions(names):
    unknown = set(names) - set(DIMENSIONS)
    if unknown:
        raise ValueError(f"未知维度: {', '.join(sorted(unknown))}")


def _build_marginal(key, members):
    return Marginal(
        key=tuple(key),
        cells=frozenset(cell_of(record) for record in members),
        headcount=len(members),
        distinct_learners=len({record["learner_id"] for record in members}),
        attendance_sum=sum((Fraction(str(record["attendance"])) for record in members), Fraction(0)),
    )


def aggregate(records, group_by, filters=None, include_total=False):
    """按给定维度分组统计；include_total 时追加一行总计（键为“合计”）。"""
    group_by = tuple(group_by)
    _check_dimensions(group_by)
    filters = dict(filters or {})
    _check_dimensions(filters)
    selected = [record for record in records
                if all(record[dimension] == value for dimension, value in filters.items())]
    groups = defaultdict(list)
    for record in selected:
        groups[tuple(record[dimension] for dimension in group_by)].append(record)
    marginals = [_build_marginal(key if key else TOTAL_KEY, groups[key])
                 for key in sorted(groups)]
    if include_total and selected and group_by:
        marginals.append(_build_marginal(TOTAL_KEY, selected))
    return marginals
