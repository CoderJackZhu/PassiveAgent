from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from passive_agent.storage.database import Database
from passive_agent.storage.models import Item
from passive_agent.utils.config import AppConfig
from passive_agent.utils.logger import log

ENGAGEMENT_EVENTS = {
    "expand",
    "read",
    "generate_card",
    "generate_note",
    "weekend",
    "link",
    "mute",
}


@dataclass
class WeeklyReport:
    week_start: date
    week_end: date
    report_path: str
    summary: dict
    suggestions: list[str] = field(default_factory=list)

    def to_card_payload(self) -> dict:
        return {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "report_path": self.report_path,
            "summary": self.summary,
            "suggestions": self.suggestions,
        }


def current_week_start(today: date | None = None) -> date:
    day = today or date.today()
    return day - timedelta(days=day.weekday())


def build_weekly_report(config: AppConfig, db: Database, today: date | None = None) -> WeeklyReport:
    day = today or date.today()
    week_start = current_week_start(day)
    week_end = min(day, week_start + timedelta(days=6))
    start_dt = datetime.combine(week_start, time.min)
    end_dt = datetime.combine(week_start + timedelta(days=7), time.min)

    events = db.get_item_events_between(start_dt, end_dt)
    items = _load_items(db, {event["item_id"] for event in events})
    archived_this_week = [
        item
        for item in db.get_items_by_stage("archived")
        if item.actioned_at and start_dt <= item.actioned_at < end_dt
    ]
    for item in archived_this_week:
        items.setdefault(item.id, item)

    first_pushed_at: dict[str, datetime] = {}
    for event in events:
        if event["event_type"] != "pushed":
            continue
        first_pushed_at.setdefault(event["item_id"], event["created_at"])

    pushed_ids = set(first_pushed_at)
    engagement_ids: set[str] = set()
    read_ids: set[str] = set()
    ignored_ids: set[str] = set()
    ignored_after_push_ids: set[str] = set()

    for event in events:
        item_id = event["item_id"]
        event_type = event["event_type"]
        if event_type == "read":
            read_ids.add(item_id)
        if event_type == "ignore":
            ignored_ids.add(item_id)
        if item_id not in pushed_ids:
            continue
        if event["created_at"] < first_pushed_at[item_id]:
            continue
        if event_type == "ignore":
            ignored_after_push_ids.add(item_id)
        if event_type in ENGAGEMENT_EVENTS:
            engagement_ids.add(item_id)

    for item in archived_this_week:
        read_ids.add(item.id)
        if item.id in pushed_ids:
            engagement_ids.add(item.id)

    passive_ids = {
        item_id
        for item_id in pushed_ids
        if item_id not in engagement_ids and item_id not in ignored_after_push_ids
    }

    daily_logs = [
        row for row in db.get_daily_logs_since(week_start)
        if date.fromisoformat(row["date"]) < week_start + timedelta(days=7)
    ]
    total_collected = sum(row["collected_count"] or 0 for row in daily_logs)
    total_processed = sum(row["processed_count"] or 0 for row in daily_logs)
    total_pushed = sum(row["pushed_count"] or 0 for row in daily_logs)
    error_days = sum(
        1 for row in daily_logs
        if row.get("status") != "paused"
        and (row.get("status") == "error" or row.get("errors"))
    )

    recommended = db.get_items_by_stage("recommended")
    stale = db.get_items_by_stage("stale")
    new = db.get_items_by_stage("new")
    retry_pending = db.get_items_by_stage("retry_pending")
    summarized = db.get_items_by_stage("summarized")

    pushed_items = _items_for_ids(items, pushed_ids)
    engaged_items = _items_for_ids(items, engagement_ids)
    read_items = _items_for_ids(items, read_ids)
    ignored_items = _items_for_ids(items, ignored_ids)
    passive_items = _items_for_ids(items, passive_ids)

    engagement_rate = (len(engagement_ids) / len(pushed_ids)) if pushed_ids else 0.0
    summary = {
        "collected": total_collected,
        "processed": total_processed,
        "daily_log_pushed": total_pushed,
        "error_days": error_days,
        "pushed_items": len(pushed_ids),
        "engaged_items": len(engagement_ids),
        "engagement_rate": engagement_rate,
        "read_items": len(read_ids),
        "ignored_items": len(ignored_ids),
        "passive_items": len(passive_ids),
        "recommended_backlog": len(recommended),
        "stale_backlog": len(stale),
        "new_summarized_backlog": len(new) + len(retry_pending) + len(summarized),
    }

    suggestions = _build_suggestions(summary, pushed_items, engaged_items, passive_items)
    markdown = render_weekly_report(
        week_start=week_start,
        week_end=week_end,
        summary=summary,
        pushed_items=pushed_items,
        engaged_items=engaged_items,
        read_items=read_items,
        ignored_items=ignored_items,
        passive_items=passive_items,
        suggestions=suggestions,
        old_processed_limit=config.display.weekly_processed_limit,
    )

    reports_dir = Path(config.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / f"weekly_review_{day.isoformat()}.md"
    output_path.write_text(markdown, encoding="utf-8")
    db.save_weekly_report(week_start=week_start, report_path=str(output_path), summary=summary)
    log.info(f"Weekly report written to {output_path}")
    return WeeklyReport(
        week_start=week_start,
        week_end=week_end,
        report_path=str(output_path),
        summary=summary,
        suggestions=suggestions,
    )


def render_weekly_report(
    *,
    week_start: date,
    week_end: date,
    summary: dict,
    pushed_items: list[Item],
    engaged_items: list[Item],
    read_items: list[Item],
    ignored_items: list[Item],
    passive_items: list[Item],
    suggestions: list[str],
    old_processed_limit: int,
) -> str:
    lines = [
        f"# 周报 · {week_start.isoformat()} ~ {week_end.isoformat()}",
        "",
        "## 概览",
        "",
        f"- 本周收集：{summary['collected']} 条",
        f"- 本周处理：{summary['processed']} 条",
        f"- 本周推送：{summary['daily_log_pushed']} 条",
        f"- 异常天数：{summary['error_days']} 天",
        f"- 当前待处理：{summary['recommended_backlog']} 条",
        f"- 已过期推荐：{summary['stale_backlog']} 条",
        f"- 新/已摘要：{summary['new_summarized_backlog']} 条",
        f"- Distinct pushed items: {summary['pushed_items']}",
        f"- Clicked/engaged: {summary['engaged_items']} ({_format_rate(summary['engagement_rate'])})",
        f"- Read: {summary['read_items']}",
        f"- Explicitly ignored: {summary['ignored_items']}",
        f"- Passive no-response: {summary['passive_items']}",
        "",
    ]

    if read_items:
        lines.extend(["## 本周处理", ""])
        for item in read_items[:old_processed_limit]:
            lines.append(f"- [{item.title[:50]}] → {item.stage}")
        lines.append("")

    lines.extend(_distribution_section("Pushed Topic Distribution", _topic_counts(pushed_items)))
    lines.extend(_distribution_section("Pushed Source Distribution", _source_counts(pushed_items)))
    lines.extend(_distribution_section("Engaged Topic Distribution", _topic_counts(engaged_items)))
    lines.extend(_distribution_section("Engaged Source Distribution", _source_counts(engaged_items)))
    lines.extend(_distribution_section("Ignored Topic Distribution", _topic_counts(ignored_items)))
    lines.extend(_distribution_section("Ignored Source Distribution", _source_counts(ignored_items)))
    lines.extend(_distribution_section("Passive Topic Distribution", _topic_counts(passive_items)))
    lines.extend(_distribution_section("Passive Source Distribution", _source_counts(passive_items)))

    lines.extend(_legacy_distribution_section("Topic 分布", _topic_counts(read_items)))
    lines.extend(_legacy_distribution_section("Source 分布", _source_counts(read_items)))

    lines.extend(["## Top Clicked/Read Items", ""])
    top_read = _unique_items(engaged_items + read_items)
    if top_read:
        for item in top_read[:10]:
            lines.append(f"- {item.title} ({item.source})")
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(["## Top Ignored/No-Response Items", ""])
    top_negative = _unique_items(ignored_items + passive_items)
    if top_negative:
        for item in top_negative[:10]:
            lines.append(f"- {item.title} ({item.source})")
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(["## Next Week Suggestions", ""])
    for suggestion in suggestions:
        lines.append(f"- {suggestion}")
    lines.extend(["", "---", f"*Generated: {week_end.isoformat()}*", ""])
    return "\n".join(lines)


def _load_items(db: Database, item_ids: set[str]) -> dict[str, Item]:
    if not item_ids:
        return {}
    placeholders = ", ".join("?" for _ in item_ids)
    rows = db.conn.execute(
        f"SELECT * FROM items WHERE id IN ({placeholders})",
        sorted(item_ids),
    ).fetchall()
    return {row["id"]: Item.from_row(dict(row)) for row in rows}


def _items_for_ids(items: dict[str, Item], item_ids: set[str]) -> list[Item]:
    found = [items[item_id] for item_id in item_ids if item_id in items]
    return sorted(found, key=lambda item: (-(item.priority_score or 0), item.title))


def _unique_items(items: list[Item]) -> list[Item]:
    seen: set[str] = set()
    unique = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    return unique


def _topic_counts(items: list[Item]) -> Counter:
    counts: Counter = Counter()
    for item in items:
        for topic in item.topics:
            counts[topic] += 1
    return counts


def _source_counts(items: list[Item]) -> Counter:
    return Counter(item.source for item in items)


def _distribution_section(title: str, counts: Counter) -> list[str]:
    lines = [f"## {title}", ""]
    if counts:
        for key, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])):
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- None")
    lines.append("")
    return lines


def _legacy_distribution_section(title: str, counts: Counter) -> list[str]:
    if not counts:
        return []
    return _distribution_section(title, counts)


def _format_rate(rate: float) -> str:
    return f"{rate:.0%}"


def _build_suggestions(
    summary: dict,
    pushed_items: list[Item],
    engaged_items: list[Item],
    passive_items: list[Item],
) -> list[str]:
    suggestions: list[str] = []
    if summary["pushed_items"] == 0:
        suggestions.append("No pushed items this week; check daily Feishu delivery before optimizing content.")
    elif summary["engagement_rate"] < 0.3:
        suggestions.append("Engagement was low; reduce push volume or tighten ranking thresholds next week.")
    else:
        suggestions.append("Keep prioritizing topics and sources that produced engagement this week.")

    engaged_topics = _topic_counts(engaged_items)
    passive_topics = _topic_counts(passive_items)
    if engaged_topics:
        topic = engaged_topics.most_common(1)[0][0]
        suggestions.append(f"Lean into engaged topic: {topic}.")
    if passive_topics:
        topic = passive_topics.most_common(1)[0][0]
        suggestions.append(f"Review passive topic volume: {topic}.")
    if pushed_items and summary["passive_items"] == 0:
        suggestions.append("No passive non-response items; current card actions are producing clear signals.")
    return suggestions[:3]
