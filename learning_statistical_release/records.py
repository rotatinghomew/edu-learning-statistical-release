import csv
from pathlib import Path

LEARNER_FIELDS = ("period", "street", "course", "learner_id", "attendance")


def read_records(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return []
    required = {"period", "group", "count", "value"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"缺少字段: {', '.join(sorted(missing))}")
    return rows


def read_learner_records(path):
    """读取本地合成的学员报名记录（合成数据，不接入真实个人资料）。"""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return []
    missing = set(LEARNER_FIELDS) - set(rows[0])
    if missing:
        raise ValueError(f"缺少字段: {', '.join(sorted(missing))}")
    records = []
    for line, row in enumerate(rows, start=2):
        try:
            attendance = float(row["attendance"])
        except ValueError as exc:
            raise ValueError(f"第 {line} 行出勤率不是数值: {row['attendance']}") from exc
        if not 0.0 <= attendance <= 1.0:
            raise ValueError(f"第 {line} 行出勤率超出 [0, 1] 范围: {attendance}")
        records.append({
            "period": row["period"],
            "street": row["street"],
            "course": row["course"],
            "learner_id": row["learner_id"],
            "attendance": attendance,
        })
    return records
