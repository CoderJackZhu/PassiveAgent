from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

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
    status: str  # success / empty / all_duplicates / error
    recommended: list[EnrichedItem] = field(default_factory=list)
    collected: int = 0
    processed: int = 0
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
            ))

        if sources.obsidian.enabled:
            collectors.append(ObsidianCollector(
                inbox_path=sources.obsidian.inbox_path,
            ))

        return collectors

    async def run(self) -> PipelineResult:
        log.info("Starting daily pipeline...")
        errors: list[str] = []
        raw_items: list[RawItem] = []

        # 0. 权重自然恢复
        feedback_engine = FeedbackEngine(self.db, self.config.scoring.negative_feedback)
        feedback_engine.recover_weights()

        # 1. Collect
        collectors = self._init_collectors()
        if not collectors:
            log.info("No collectors enabled.")
            self.db.log_daily_run(date.today(), 0, 0, 0, [])
            return PipelineResult(status="empty")

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

        if not raw_items:
            log.info("No new items collected from any source.")
            self.db.log_daily_run(date.today(), 0, 0, 0, errors)
            if errors:
                return PipelineResult(status="error", errors=errors)
            return PipelineResult(status="empty")

        # 2. Normalize
        items = self.normalizer.normalize(raw_items)
        log.info(f"Normalized {len(items)} items")

        # 3. Dedup
        new_items = self.deduplicator.filter(items)
        if not new_items:
            log.info("All items are duplicates.")
            self.db.log_daily_run(date.today(), len(raw_items), 0, 0, errors)
            return PipelineResult(status="all_duplicates", collected=len(raw_items))

        # 4-6. Summarize → Score → Rank (需要 LLM)
        if self.llm is None:
            # 无 LLM，仅保存原始数据
            self.db.save_items(new_items)
            log.info(f"Saved {len(new_items)} new items (no LLM configured)")
            self.db.log_daily_run(date.today(), len(raw_items), len(new_items), 0, errors)
            return PipelineResult(status="success", collected=len(raw_items), processed=len(new_items))

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
        ranker = Ranker(self.db, self.config.scoring.daily_limit)
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
                self.feishu_bot.send_daily_card(enriched)
            except Exception as e:
                log.error(f"Feishu push failed: {e}")
                errors.append(f"Feishu push: {e}")

        # 11. Zotero write-back (flush pending tag writes)
        if self.config.sources.zotero.writeback_enabled:
            try:
                from passive_agent.integrations.zotero_writeback import ZoteroWriteBack
                if ZoteroWriteBack.is_available():
                    wb = ZoteroWriteBack(self.db, dry_run=False)
                    await wb.flush_queue()
            except Exception as e:
                log.warning(f"Zotero write-back skipped: {e}")
        else:
            try:
                from passive_agent.integrations.zotero_writeback import ZoteroWriteBack
                if ZoteroWriteBack.is_available():
                    wb = ZoteroWriteBack(self.db, dry_run=True)
                    await wb.flush_queue()
            except Exception as e:
                pass

        # 12. Log
        self.db.log_daily_run(date.today(), len(raw_items), len(new_items), len(top_items), errors)

        return PipelineResult(
            status="success",
            recommended=enriched,
            collected=len(raw_items),
            processed=len(new_items),
            errors=errors,
        )

    def _output_daily_review(self, enriched: list[EnrichedItem]):
        reports_dir = Path(self.config.reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_path = reports_dir / f"daily_review_{date.today().isoformat()}.md"

        lines = [f"# 今日推荐 · {date.today().strftime('%Y-%m-%d')}\n"]

        for i, e in enumerate(enriched, 1):
            item = e.item
            lines.append(f"## {i}. {item.title}\n")
            lines.append(f"- **来源**: {item.source}")
            lines.append(f"- **预计**: {item.estimated_minutes or '?'} 分钟")
            lines.append(f"- **面试价值**: {item.interview_relevance or '未知'}")
            lines.append(f"- **综合评分**: {item.priority_score:.1f}/100")
            lines.append(f"- **建议**: {item.recommended_action or 'read'}")
            if item.summary:
                lines.append(f"- **摘要**: {item.summary}")
            if item.url:
                lines.append(f"- **链接**: {item.url}")
            if e.related_zotero:
                lines.append(f"- **相关旧文章**: {', '.join(e.related_zotero)}")
            lines.append("")

        lines.append("---\n")
        lines.append(f"*共收集 {len(enriched)} 条推荐，ID: {', '.join(e.item.id for e in enriched)}*\n")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"Daily review written to {output_path}")


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

    week_archived = [i for i in archived if i.actioned_at and i.actioned_at.date() >= week_start]
    week_ignored = [i for i in ignored if i.created_at.date() >= week_start]

    # Topic distribution
    topic_counts: dict[str, int] = {}
    for item in week_archived:
        for topic in item.topics:
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    lines = [
        f"# 周报 · {week_start.isoformat()} ~ {today.isoformat()}\n",
        f"## 概览\n",
        f"- 已处理归档：{len(week_archived)} 条",
        f"- 已忽略：{len(week_ignored)} 条",
        f"- 当前待处理：{len(recommended)} 条",
        "",
    ]

    if week_archived:
        lines.append("## 本周处理\n")
        for item in week_archived[:10]:
            lines.append(f"- [{item.title[:50]}] → {item.stage}")
        lines.append("")

    if topic_counts:
        lines.append("## Topic 分布\n")
        for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {topic}: {count}")
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
