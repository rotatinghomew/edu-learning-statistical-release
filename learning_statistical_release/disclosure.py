"""跨查询披露判断。

单张表内部的小单元遮蔽（operations.review）并不够：同一接收者手里的
多张精确结果可以相减，反推出被遮住的单元。本模块把每次发布转化为
基础单元（期次 × 街道 × 课程）上的线性方程——人数与出勤总和都是可加
指标——再用精确有理数行空间判断：在“该接收范围已见结果 + 本次候选
结果”之下，受保护单元是否会被唯一确定。

公开约定：人数或去重学员数低于 MIN_PUBLISHABLE_COUNT 的单元不予公开；
受保护单元输出为“不予公开”占位，绝不输出 0；已发出的确定数值不回写。
"""
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metrics import Marginal

MIN_PUBLISHABLE_COUNT = 3  # 项目公开约定：最小可公开人数（保护下限）

RELEASED = "公开"
SUPPRESSED = "不予公开"
REASON_BELOW_MIN = "低于最小可公开人数"
REASON_COMBINABLE = "与已公开结果合并后可反推受保护单元"


class LinearBasis:
    """精确有理数行空间（约化行阶梯形），判断目标向量是否已被确定。"""

    def __init__(self):
        self._pivots = {}  # 主元列 -> 归一化行向量（dict）

    def copy(self):
        other = LinearBasis()
        other._pivots = {pivot: dict(row) for pivot, row in self._pivots.items()}
        return other

    def _reduce(self, vector):
        vec = {key: Fraction(value) for key, value in vector.items() if value}
        for pivot in sorted(self._pivots):
            if pivot in vec:
                row = self._pivots[pivot]
                factor = vec[pivot]
                for column, coefficient in row.items():
                    vec[column] = vec.get(column, Fraction(0)) - factor * coefficient
                    if vec[column] == 0:
                        del vec[column]
        return vec

    def add(self, vector):
        """加入一个方程向量；已在行空间内则返回 False。"""
        vec = self._reduce(vector)
        if not vec:
            return False
        pivot = min(vec)
        coefficient = vec[pivot]
        normalized = {key: value / coefficient for key, value in vec.items()}
        for row in self._pivots.values():
            if pivot in row:
                factor = row[pivot]
                for column, value in normalized.items():
                    row[column] = row.get(column, Fraction(0)) - factor * value
                    if row[column] == 0:
                        del row[column]
        self._pivots[pivot] = normalized
        return True

    def determines(self, vector):
        """目标向量是否落在行空间内（即其数值被既有方程唯一确定）。"""
        return not self._reduce(vector)


def _n_vector(cells):
    return {("n",) + tuple(cell): Fraction(1) for cell in cells}


def _s_vector(cells):
    return {("s",) + tuple(cell): Fraction(1) for cell in cells}


def _vectors_of(marginal):
    return [_n_vector(marginal.cells), _s_vector(marginal.cells)]


def small_cell_targets(cell_counts, min_count=MIN_PUBLISHABLE_COUNT):
    """人数低于下限的基础单元：其人数与出勤总和都受保护。"""
    targets = []
    for cell, count in sorted(cell_counts.items()):
        if count < min_count:
            targets.append(_n_vector([cell]))
            targets.append(_s_vector([cell]))
    return targets


@dataclass
class RowDecision:
    marginal: "Marginal"
    released: bool | None
    reason: str | None = None


def evaluate_marginals(marginals, released_vectors, protected_vectors,
                       min_count=MIN_PUBLISHABLE_COUNT):
    """判断一组边际中哪些可以同时公开。

    released_vectors：该接收范围已公开结果对应的方程向量。
    protected_vectors：受保护目标（全局小单元 + 该范围此前被遮蔽的边际）。

    返回 (decisions, new_released, new_protected)，decisions 与输入同序；
    new_released / new_protected 供写入该接收范围的台账。宁可保留空缺也
    不公开会暴露受保护单元的数值。
    """
    basis = LinearBasis()
    for vector in released_vectors:
        basis.add(vector)
    protected = list(protected_vectors)
    decisions = []
    new_released = []
    new_protected = []

    for marginal in marginals:
        reason = None
        if marginal.headcount < min_count:
            reason = f"人数{REASON_BELOW_MIN}"
        elif marginal.distinct_learners < min_count:
            reason = f"去重学员数{REASON_BELOW_MIN}"
        if reason is None:
            decisions.append(RowDecision(marginal, None))
            continue
        decisions.append(RowDecision(marginal, False, reason))
        vectors = _vectors_of(marginal)
        protected += vectors
        new_protected += vectors

    for decision in decisions:
        if decision.released is not None:
            continue
        vectors = _vectors_of(decision.marginal)
        trial = basis.copy()
        for vector in vectors:
            trial.add(vector)
        if any(trial.determines(target) and not basis.determines(target)
               for target in protected):
            decision.released = False
            decision.reason = REASON_COMBINABLE
            protected += vectors
            new_protected += vectors
        else:
            decision.released = True
            basis = trial
            new_released += vectors
    return decisions, new_released, new_protected
