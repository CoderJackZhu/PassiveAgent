from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from passive_agent.collectors.hf_daily import HFDailyPapersCollector
from passive_agent.collectors.obsidian import ObsidianCollector
from passive_agent.collectors.zotero import ZoteroCollector
from passive_agent.integrations.deepseek import DeepSeekClient
from passive_agent.processors.deduplicator import Deduplicator
from passive_agent.processors.feedback_engine import FeedbackEngine
from passive_agent.processors.normalizer import Normalizer
from passive_agent.processors.ranker import Ranker
from passive_agent.processors.scorer import Scorer
from passive_agent.processors.summarizer import Summarizer
from passive_agent.storage.database import Database
from passive_agent.storage.models import EnrichedItem, RawItem
from passive_agent.utils.config import AppConfig
from passive_agent.utils.logger import log


@dataclass
class PipelineResult:
    status: str  # success / empty / all_duplicates / paused / error
    recommended: list[EnrichedItem] = field(default_factory=list)
    collected: int = 0
    processed: int = 0
    pushed: int = 0
    stale: int = 0
    errors: list[str] = field(default_factory=list)


class DailyPipeline:
    def __init__(self, config: AppConfig, db: Database, llm: DeepSeekClient | None = None,
                 feishu_bot=None):
        self.config = config
        self.db = db
        self.llm = llm
        self.feishu_bot = feishu_bot
        self.prompts_dir = str(Path(config.project_root) / config.prompts_dir) if config.project_root else config.prompts_dir
        self.normalizer = Normalizer(db, config.sources.zotero.high_priority_collections)
        self.deduplicator = Deduplicator(db)

    def _init_collectors(self) -> list:
        collectors = []
        sources = self.config.sources

        if sources.zotero.enabled:
            collectors.append(ZoteroCollector(
                db_path=sources.zotero.db_path,
                lookback_days=sources.zotero.lookback_days,
                sqlite_timeout_seconds=sources.zotero.sqlite_timeout_seconds,
                db_retries=sources.zotero.db_retries,
                db_retry_sleep_seconds=sources.zotero.db_retry_sleep_seconds,
            ))

        if sources.obsidian.enabled:
            collectors.append(ObsidianCollector(
                inbox_path=sources.obsidian.inbox_path,
            ))

        if sources.hf_daily.enabled:
            collectors.append(HFDailyPapersCollector(
                max_papers=sources.hf_daily.max_papers,
                days=sources.hf_daily.lookback_days,
                timeout_seconds=sources.hf_daily.http_timeout_seconds,
            ))

        return collectors

    async def run(self) -> PipelineResult:
        log.info("Starting daily pipeline...")
        errors: list[str] = []
        raw_items: list[RawItem] = []
        collected_count = 0
        processed_count = 0
        pushed_count = 0
        stale_count = 0

        if self.db.is_paused():
            log.info("Daily pipeline is paused, skipping collection and push.")
            self.db.log_daily_run(date.today(), 0, 0, 0, [], status="paused")
            return PipelineResult(status="paused")

        try:
            # 0. 权重自然恢复 + 过期推荐清理
            feedback_engine = FeedbackEngine(self.db, self.config.scoring.negative_feedback)
            feedback_engine.recover_weights()
            stale_count = self.db.mark_stale_recommendations(
                days=self.config.recommendations.stale_after_days
            )
            if stale_count:
                log.info(f"Marked {stale_count} stale recommendations")

            # 1. Collect
            collectors = self._init_collectors()
            if not collectors:
                log.info("No collectors enabled.")
                self.db.log_daily_run(date.today(), 0, 0, 0, [], status="empty")
                return PipelineResult(status="empty", stale=stale_count)

            for collector in collectors:
                if not collector.is_available():
                    path = getattr(collector, "inbox_path", None) or getattr(collector, "db_path", None)
                    detail = f" ({path})" if path else ""
                    log.info(f"{collector.__class__.__name__}: not available{detail}, skipping")
                    continue
                try:
                    items = await collector.collect()
                    raw_items.extend(items)
                except Exception as e:
                    msg = f"{collector.__class__.__name__}: {e}"
                    log.error(msg)
                    errors.append(msg)

            collected_count = len(raw_items)
            if not raw_items:
                log.info("No new items collected from any source.")
                status = "error" if errors else "empty"
                self.db.log_daily_run(date.today(), 0, 0, 0, errors, status=status)
                return PipelineResult(status=status, errors=errors, stale=stale_count)

            # 2. Normalize
            items = self.normalizer.normalize(raw_items)
            log.info(f"Normalized {len(items)} items")

            # 3. Dedup
            new_items = self.deduplicator.filter(items)
            processed_count = len(new_items)
            if not new_items:
                log.info("All items are duplicates.")
                self.db.log_daily_run(date.today(), collected_count, 0, 0, errors, status="all_duplicates")
                return PipelineResult(
                    status="all_duplicates",
                    collected=collected_count,
                    errors=errors,
                    stale=stale_count,
                )

            # 4-6. Summarize → Score → Rank (需要 LLM)
            if self.llm is None:
                # 无 LLM，仅保存原始数据
                self.db.save_items(new_items)
                log.info(f"Saved {len(new_items)} new items (no LLM configured)")
                self.db.log_daily_run(date.today(), collected_count, processed_count, 0, errors, status="success")
                return PipelineResult(
                    status="success",
                    collected=collected_count,
                    processed=processed_count,
                    errors=errors,
                    stale=stale_count,
                )

            # 4. Summarize
            summarizer = Summarizer(self.llm, self.config.goals, self.prompts_dir)
            summarized = await summarizer.summarize_batch(new_items)

            # 保存已摘要的条目（scorer 的 save_score 需要 items 表中有记录）
            self.db.save_items(summarized)

            # 5. Score
            scorer = Scorer(self.llm, self.config.goals, self.config.scoring, self.db,
                            prompts_dir=self.prompts_dir,
                            high_priority_collections=self.config.sources.zotero.high_priority_collections)
            scored = await scorer.score_batch(summarized)

            # 6. Rank + Top N
            ranker = Ranker(
                self.db,
                self.config.scoring.daily_limit,
                related_zotero_limit=self.config.recommendations.related_zotero_limit,
                related_stars_limit=self.config.recommendations.related_stars_limit,
            )
            top_items = ranker.select_top(scored)

            # 7. Enrich
            enriched = ranker.enrich(top_items)

            # 8. 持久化所有已处理条目
            for item in scored:
                if item not in top_items:
                    item.stage = "summarized"
            for item in top_items:
                item.stage = "recommended"
            self.db.save_items(scored)

            # 9. 输出本地报告
            self._output_daily_review(enriched)

            # 10. 飞书推送（如果配置了）
            if self.feishu_bot:
                try:
                    if self.feishu_bot.send_daily_card(enriched):
                        pushed_count = len(enriched)
                    else:
                        msg = "Feishu push: returned False"
                        log.error(msg)
                        errors.append(msg)
                except Exception as e:
                    log.error(f"Feishu push failed: {e}")
                    errors.append(f"Feishu push: {e}")

            # 11. Zotero write-back (flush pending tag writes)
            if self.config.sources.zotero.writeback_enabled:
                try:
                    from passive_agent.integrations.zotero_writeback import ZoteroWriteBack
                    if ZoteroWriteBack.is_available(
                        local_api_timeout_seconds=self.config.sources.zotero.local_api_timeout_seconds
                    ):
                        wb = ZoteroWriteBack(
                            self.db,
                            dry_run=False,
                            writeback_timeout_seconds=self.config.sources.zotero.writeback_timeout_seconds,
                            local_api_timeout_seconds=self.config.sources.zotero.local_api_timeout_seconds,
                        )
                        await wb.flush_queue()
                except Exception as e:
                    log.warning(f"Zotero write-back skipped: {e}")
            else:
                try:
                    from passive_agent.integrations.zotero_writeback import ZoteroWriteBack
                    if ZoteroWriteBack.is_available(
                        local_api_timeout_seconds=self.config.sources.zotero.local_api_timeout_seconds
                    ):
                        wb = ZoteroWriteBack(
                            self.db,
                            dry_run=True,
                            writeback_timeout_seconds=self.config.sources.zotero.writeback_timeout_seconds,
                            local_api_timeout_seconds=self.config.sources.zotero.local_api_timeout_seconds,
                        )
                        await wb.flush_queue()
                except Exception:
                    pass

            # 12. Log
            self.db.log_daily_run(date.today(), collected_count, processed_count, pushed_count, errors, status="success")

            return PipelineResult(
                status="success",
                recommended=enriched,
                collected=collected_count,
                processed=processed_count,
                pushed=pushed_count,
                stale=stale_count,
                errors=errors,
            )
        except Exception as e:
            msg = f"Pipeline: {e}"
            log.exception("Daily pipeline failed")
            errors.append(msg)
            self.db.log_daily_run(
                date.today(),
                collected_count,
                processed_count,
                pushed_count,
                errors,
                status="error",
            )
            return PipelineResult(
                status="error",
                collected=collected_count,
                processed=processed_count,
                pushed=pushed_count,
                stale=stale_count,
                errors=errors,
            )

    def _output_daily_review(self, enriched: list[EnrichedItem]):
        reports_dir = Path(self.config.reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_path = reports_dir / f"daily_review_{date.today().isoformat()}.md"

        lines = [f"# 今日推荐 · {date.today().strftime('%Y-%m-%d')}\n"]

        source_counts = Counter(e.item.source for e in enriched)
        total_minutes = sum(e.item.estimated_minutes or 0 for e in enriched)
        scores = [e.item.priority_score for e in enriched if e.item.priority_score is not None]
        score_text = (
            f"{min(scores):.1f} ~ {max(scores):.1f}，平均 {sum(scores) / len(scores):.1f}"
            if scores else "暂无评分"
        )

        lines.append("## 概览\n")
        lines.append(f"- 推荐数量：{len(enriched)} 条")
        lines.append(f"- 总预计时间：{total_minutes} 分钟")
        lines.append(f"- 来源分布：{_format_counts(source_counts)}")
        lines.append(f"- 评分范围：{score_text}")
        lines.append("")

        lines.append("## 今日行动建议\n")
        if enriched:
            for i, e in enumerate(enriched, 1):
                item = e.item
                minutes = item.estimated_minutes or "?"
                lines.append(f"- {i}. {item.recommended_action or 'read'}：{item.title}（{minutes} 分钟）")
        else:
            lines.append("- 暂无推荐")
        lines.append("")

        lines.append("## 条目详情\n")

        for i, e in enumerate(enriched, 1):
            item = e.item
            lines.append(f"## {i}. {item.title}\n")
            lines.append(f"- **来源**: {item.source}")
            lines.append(f"- **预计**: {item.estimated_minutes or '?'} 分钟")
            lines.append(f"- **面试价值**: {item.interview_relevance or '未知'}")
            score = f"{item.priority_score:.1f}/100" if item.priority_score is not None else "未评分"
            lines.append(f"- **综合评分**: {score}")
            lines.append(f"- **建议**: {item.recommended_action or 'read'}")
            if item.summary:
                lines.append(f"- **摘要**: {item.summary}")
            if item.url:
                lines.append(f"- **链接**: {item.url}")
            if e.related_zotero:
                lines.append(f"- **相关旧文章**: {', '.join(e.related_zotero)}")
            if e.related_stars:
                lines.append(f"- **相关 GitHub Star**: {', '.join(e.related_stars)}")
            lines.append("")

        lines.append("---\n")
        lines.append(f"*共收集 {len(enriched)} 条推荐，ID: {', '.join(e.item.id for e in enriched)}*\n")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"Daily review written to {output_path}")


def _format_counts(counts) -> str:
    if not counts:
        return "无"
    return "，".join(f"{key}: {count}" for key, count in sorted(counts.items()))


def run_pipeline(config: AppConfig, db: Database) -> PipelineResult:
    pipeline = DailyPipeline(config, db)
    return asyncio.run(pipeline.run())


def generate_weekly_report(config: AppConfig, db: Database) -> str:
    """生成周报 Markdown 并写入 reports 目录"""
    from datetime import timedelta

    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    archived = db.get_items_by_stage("archived")
    ignored = db.get_items_by_stage("ignored")
    recommended = db.get_items_by_stage("recommended")
    stale = db.get_items_by_stage("stale")
    new = db.get_items_by_stage("new")
    summarized = db.get_items_by_stage("summarized")
    daily_logs = db.get_daily_logs_since(week_start)

    week_archived = [i for i in archived if i.actioned_at and i.actioned_at.date() >= week_start]
    week_ignored = [i for i in ignored if i.created_at.date() >= week_start]

    total_collected = sum(log_row["collected_count"] or 0 for log_row in daily_logs)
    total_processed = sum(log_row["processed_count"] or 0 for log_row in daily_logs)
    total_pushed = sum(log_row["pushed_count"] or 0 for log_row in daily_logs)
    error_days = sum(
        1 for log_row in daily_logs
        if log_row.get("status") != "paused"
        and (log_row.get("status") == "error" or log_row.get("errors"))
    )

    # Topic/source distribution for items actually handled this week.
    topic_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for item in week_archived:
        source_counts[item.source] = source_counts.get(item.source, 0) + 1
        for topic in item.topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    lines = [
        f"# 周报 · {week_start.isoformat()} ~ {today.isoformat()}\n",
        f"## 概览\n",
        f"- 本周收集：{total_collected} 条",
        f"- 本周处理：{total_processed} 条",
        f"- 本周推送：{total_pushed} 条",
        f"- 异常天数：{error_days} 天",
        f"- 已处理归档：{len(week_archived)} 条",
        f"- 已忽略：{len(week_ignored)} 条",
        f"- 当前待处理：{len(recommended)} 条",
        f"- 已过期推荐：{len(stale)} 条",
        f"- 新/已摘要：{len(new) + len(summarized)} 条",
        "",
    ]

    if week_archived:
        lines.append("## 本周处理\n")
        for item in week_archived[:config.display.weekly_processed_limit]:
            lines.append(f"- [{item.title[:50]}] → {item.stage}")
        lines.append("")

    if topic_counts:
        lines.append("## Topic 分布\n")
        for topic, count in sorted(topic_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {topic}: {count}")
        lines.append("")

    if source_counts:
        lines.append("## Source 分布\n")
        for source, count in sorted(source_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- {source}: {count}")
        lines.append("")

    # Weight changes
    rows = db.conn.execute(
        "SELECT topic, weight FROM topic_weights WHERE weight < 1.0"
    ).fetchall()
    if rows:
        lines.append("## 降权 Topics\n")
        for r in rows:
            lines.append(f"- {r['topic']}: {r['weight']:.2f}")
        lines.append("")

    lines.append(f"\n---\n*Generated: {today.isoformat()}*\n")

    reports_dir = Path(config.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    output_path = reports_dir / f"weekly_review_{today.isoformat()}.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Weekly report written to {output_path}")
    return str(output_path)
