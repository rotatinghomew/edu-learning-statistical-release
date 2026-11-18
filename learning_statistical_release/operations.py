from .disclosure import MIN_PUBLISHABLE_COUNT


def review(summary, minimum_count=MIN_PUBLISHABLE_COUNT):
    return [{**row, "review": "可查看" if row["count"] >= minimum_count else "资料不足"}
            for row in summary]
