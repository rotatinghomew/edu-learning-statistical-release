"""统计查询、订阅交付与审计。

- 查询与订阅交付共用同一套披露判断（disclosure.evaluate_marginals）。
- 每次交付写入对应“接收范围”的台账；之后的判断必须兼容已发出的结果，
  已发出的确定数值不回写、不悄悄修改。
- 订阅在运行时才重新判断接收范围；预览通过不代表交付时仍可公开。
- 业务人员可查精确内部统计、全部交付记录与拒绝原因；收件人只能查自己
  接收范围内的交付记录。

服务对象对应一个数据版次；新版次需新建服务对象，旧版次的交付承诺不跨
版次沿用，也不回写旧版次的消息。
"""
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass

from .disclosure import (MIN_PUBLISHABLE_COUNT, RELEASED, SUPPRESSED,
                         evaluate_marginals, small_cell_targets)
from .metrics import aggregate, cell_of

ROLE_STAFF = "staff"
ROLE_RECIPIENT = "recipient"

STATUS_FULL = "公开"
STATUS_PARTIAL = "部分公开"
STATUS_REFUSED = "拒绝"


@dataclass(frozen=True)
class Actor:
    """调用者：业务人员（staff）或携带接收范围的收件人（recipient）。"""

    name: str
    role: str
    scope: str | None = None

    def __post_init__(self):
        if self.role not in (ROLE_STAFF, ROLE_RECIPIENT):
            raise ValueError(f"未知角色: {self.role}")
        if self.role == ROLE_RECIPIENT and not self.scope:
            raise ValueError("收件人必须携带接收范围")


@dataclass(frozen=True)
class DeliveredRow:
    """实际交付的一行；受保护行为“不予公开”，数值为空且绝不为 0。"""

    key: tuple
    status: str
    headcount: int | None
    distinct_learners: int | None
    mean_attendance: float | None
    reason: str | None


@dataclass(frozen=True)
class Delivery:
    """一次交付（含拒绝）；记录不可变，只追加。"""

    seq: int
    data_version: str
    scope: str
    label: str
    status: str
    rows: tuple
    reasons: tuple


@dataclass(frozen=True)
class Subscription:
    sub_id: int
    scope: str
    label: str
    group_by: tuple
    filters: tuple
    include_total: bool


def data_fingerprint(records):
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: (cell_of(item), item["learner_id"])):
        digest.update(repr((cell_of(record), record["learner_id"],
                            record["attendance"])).encode("utf-8"))
    return digest.hexdigest()[:12]


def _default_label(group_by, filters):
    parts = [f"{key}={value}" for key, value in sorted((filters or {}).items())]
    if group_by:
        parts.append("按" + "、".join(group_by) + "分组")
    return "统计查询（" + "；".join(parts) + "）" if parts else "统计查询（全部记录）"


class ReleaseService:
    """同一数据版次上的查询、订阅与审计。"""

    def __init__(self, records, min_count=MIN_PUBLISHABLE_COUNT, data_version=None):
        self._records = list(records)
        self._min_count = min_count
        self.data_version = data_version or data_fingerprint(self._records)
        cell_counts = Counter(cell_of(record) for record in self._records)
        self._global_protected = small_cell_targets(cell_counts, min_count)
        self._released = defaultdict(list)   # scope -> 已公开方程向量
        self._protected = defaultdict(list)  # scope -> 受保护目标向量
        self._deliveries = []                # 交付日志（只追加，不回写）
        self._subscriptions = []
        self._seq = 0

    # —— 查询与订阅 ——

    def query(self, actor, group_by, filters=None, include_total=False,
              label=None, scope=None):
        """即席查询：判断通过的部分立即交付并记入台账。"""
        scope = self._resolve_scope(actor, scope)
        marginals = aggregate(self._records, group_by, filters, include_total)
        return self._release(scope, marginals, label or _default_label(group_by, filters),
                             record=True)

    def preview(self, actor, group_by, filters=None, include_total=False,
                label=None, scope=None):
        """预览：只判断不记账；预览通过不代表交付时仍可公开。"""
        scope = self._resolve_scope(actor, scope)
        marginals = aggregate(self._records, group_by, filters, include_total)
        return self._release(scope, marginals, label or _default_label(group_by, filters),
                             record=False)

    def subscribe(self, actor, group_by, filters=None, include_total=False,
                  label=None, scope=None):
        """登记订阅并返回预览；交付以运行时重新判断为准。"""
        scope = self._resolve_scope(actor, scope)
        subscription = Subscription(
            sub_id=len(self._subscriptions) + 1,
            scope=scope,
            label=label or _default_label(group_by, filters),
            group_by=tuple(group_by),
            filters=tuple(sorted((filters or {}).items())),
            include_total=include_total,
        )
        self._subscriptions.append(subscription)
        return subscription, self.preview(actor, group_by, filters, include_total,
                                          label, scope)

    def run_subscriptions(self):
        """订阅交付：运行时按当前台账重新判断接收范围。"""
        deliveries = []
        for subscription in self._subscriptions:
            marginals = aggregate(self._records, subscription.group_by,
                                  dict(subscription.filters), subscription.include_total)
            deliveries.append(self._release(subscription.scope, marginals,
                                            f"{subscription.label}（订阅交付）", record=True))
        return deliveries

    # —— 审计 ——

    def internal_stats(self, actor, group_by, filters=None):
        """业务人员专用的精确内部统计（不做任何遮蔽）。"""
        self._require_staff(actor)
        return aggregate(self._records, group_by, filters)

    def deliveries(self, actor, scope=None):
        """交付记录：业务人员看全部，收件人只能看自己的接收范围。"""
        if actor.role == ROLE_STAFF:
            return [delivery for delivery in self._deliveries
                    if scope is None or delivery.scope == scope]
        if scope is not None and scope != actor.scope:
            raise PermissionError("收件人只能查询自己的交付记录")
        return [delivery for delivery in self._deliveries if delivery.scope == actor.scope]

    # —— 内部 ——

    def _release(self, scope, marginals, label, record):
        if not marginals:
            return self._register(scope, label, STATUS_REFUSED, (),
                                  ("没有匹配的记录",), record)
        decisions, new_released, new_protected = evaluate_marginals(
            marginals,
            self._released[scope],
            self._global_protected + self._protected[scope],
            self._min_count,
        )
        rows = tuple(self._to_row(decision) for decision in decisions)
        released_count = sum(1 for decision in decisions if decision.released)
        if released_count == len(decisions):
            status = STATUS_FULL
        elif released_count:
            status = STATUS_PARTIAL
        else:
            status = STATUS_REFUSED
        reasons = tuple(sorted({decision.reason for decision in decisions if decision.reason}))
        if record:
            self._released[scope] += new_released
            self._protected[scope] += new_protected
        return self._register(scope, label, status, rows, reasons, record)

    def _register(self, scope, label, status, rows, reasons, record):
        self._seq += 1
        delivery = Delivery(self._seq, self.data_version, scope, label, status,
                            rows, reasons)
        if record:
            self._deliveries.append(delivery)
        return delivery

    @staticmethod
    def _to_row(decision):
        marginal = decision.marginal
        if decision.released:
            return DeliveredRow(marginal.key, RELEASED, marginal.headcount,
                                marginal.distinct_learners, marginal.mean_attendance, None)
        return DeliveredRow(marginal.key, SUPPRESSED, None, None, None, decision.reason)

    @staticmethod
    def _resolve_scope(actor, scope):
        if actor.role == ROLE_RECIPIENT:
            if scope is not None and scope != actor.scope:
                raise PermissionError("收件人只能在自己的接收范围内查询")
            return actor.scope
        if scope is None:
            raise ValueError("业务人员代为查询时必须指定接收范围")
        return scope

    @staticmethod
    def _require_staff(actor):
        if actor.role != ROLE_STAFF:
            raise PermissionError("只有业务人员可以查看精确内部统计")
