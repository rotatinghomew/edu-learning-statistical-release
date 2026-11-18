import tempfile
from pathlib import Path

from .analysis import summarize
from .operations import review
from .records import read_learner_records, read_records
from .service import Actor, ReleaseService
from .storage import replace_records

DATA_DIR = Path(__file__).parent.parent / "data"


def _print_delivery(delivery):
    print(f"[{delivery.status}] {delivery.label}"
          f"（接收范围 {delivery.scope}，版次 {delivery.data_version}）")
    for row in delivery.rows:
        key = "/".join(row.key)
        if row.status == "公开":
            print(f"  {key}: 人数 {row.headcount}，去重学员 {row.distinct_learners}，"
                  f"平均出勤率 {row.mean_attendance:.2f}")
        else:
            print(f"  {key}: 不予公开（{row.reason}）")
    for reason in delivery.reasons:
        print(f"  说明: {reason}")


def main():
    data = DATA_DIR / "observations.csv"
    rows = read_records(data)
    with tempfile.TemporaryDirectory() as directory:
        stored = replace_records(Path(directory) / "observations.db", rows)
        rows = [{"period": period, "group": group, "count": count, "value": value}
                for period, group, count, value in stored]
    print("—— 观测摘要（单表检查） ——")
    for row in review(summarize(rows)):
        print(f"{row['period']} {row['group']}: {row['count']} 条，"
              f"均值 {row['mean']:.2f}，{row['review']}")

    print("\n—— 老年学习统计的跨查询披露判断 ——")
    records = read_learner_records(DATA_DIR / "learners.csv")
    service = ReleaseService(records)
    staff = Actor("运营专员", "staff")
    south = Actor("城南街道负责人", "recipient", scope="street:城南街道")
    calligraphy = Actor("书法班负责人", "recipient", scope="course:书法班")

    _print_delivery(service.query(
        south, ["course"], {"period": "2026-S1", "street": "城南街道"},
        include_total=True, label="城南街道分课程统计"))
    _print_delivery(service.query(
        south, [], {"period": "2026-S1", "street": "城南街道"}, label="城南街道合计"))

    subscription, preview = service.subscribe(
        calligraphy, ["street"], {"period": "2026-S1", "course": "书法班"},
        label="书法班分街道统计")
    print("\n订阅预览（不记账，交付以运行时为准）:")
    _print_delivery(preview)
    _print_delivery(service.query(
        calligraphy, [], {"period": "2026-S1", "course": "书法班"}, label="书法班合计"))
    print("\n订阅运行时重新判断:")
    for delivery in service.run_subscriptions():
        _print_delivery(delivery)

    print("\n—— 审计 ——")
    for marginal in service.internal_stats(
            staff, ["course"], {"period": "2026-S1", "street": "城西街道"}):
        print(f"内部精确值 {'/'.join(marginal.key)}: 人数 {marginal.headcount}，"
              f"去重学员 {marginal.distinct_learners}，"
              f"平均出勤率 {marginal.mean_attendance:.2f}")
    print(f"业务人员可见交付记录 {len(service.deliveries(staff))} 条；"
          f"书法班负责人可见自己的 {len(service.deliveries(calligraphy))} 条")


if __name__ == "__main__":
    main()
