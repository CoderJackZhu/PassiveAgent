from __future__ import annotations

from passive_agent.processors.ranker import Ranker
from passive_agent.storage.database import Database
from passive_agent.utils.logger import log


class CommandHandler:
    """处理飞书文本消息命令"""

    COMMANDS = {
        "本周总结": "_cmd_weekly_summary",
        "周末队列": "_cmd_weekend_queue",
        "最近卡片": "_cmd_recent_cards",
        "状态": "_cmd_status",
        "暂停": "_cmd_pause",
        "恢复": "_cmd_resume",
        "推送": "_cmd_push",
        "详情": "_cmd_detail",
    }

    def __init__(self, db: Database):
        self.db = db

    def is_paused(self) -> bool:
        return self.db.is_paused()

    async def handle(self, text: str) -> str | None:
        text = text.strip()
        for keyword, method_name in self.COMMANDS.items():
            if keyword in text:
                method = getattr(self, method_name)
                if method_name == "_cmd_detail":
                    return await method(text)
                return await method()

        return "支持的命令：本周总结 / 周末队列 / 最近卡片 / 状态 / 暂停 / 恢复 / 推送 / 详情 <item_id>"

    async def _cmd_weekly_summary(self) -> str:
        archived = self.db.get_items_by_stage("archived")
        ignored = self.db.get_items_by_stage("ignored")
        recommended = self.db.get_items_by_stage("recommended")
        stale = self.db.get_items_by_stage("stale")

        cards = [i for i in archived if i.actioned_at]
        return (
            f"本周总结：\n"
            f"- 已处理：{len(archived)} 条\n"
            f"- 已忽略：{len(ignored)} 条\n"
            f"- 待处理：{len(recommended)} 条\n"
            f"- 已过期推荐：{len(stale)} 条\n"
            f"- 生成卡片/笔记：{len(cards)} 张"
        )

    async def _cmd_weekend_queue(self) -> str:
        rows = self.db.conn.execute(
            "SELECT title FROM items WHERE is_weekend = 1 AND stage NOT IN ('archived', 'ignored')"
        ).fetchall()

        if not rows:
            return "周末队列为空"

        items_text = "\n".join(f"  {i+1}. {r['title']}" for i, r in enumerate(rows))
        return f"周末队列 ({len(rows)} 篇)：\n{items_text}"

    async def _cmd_recent_cards(self) -> str:
        rows = self.db.conn.execute(
            "SELECT title FROM items WHERE stage = 'archived' ORDER BY actioned_at DESC LIMIT 5"
        ).fetchall()

        if not rows:
            return "暂无已生成的卡片"

        items_text = "\n".join(f"  · {r['title']}" for r in rows)
        return f"最近卡片：\n{items_text}"

    async def _cmd_status(self) -> str:
        stages = {}
        for stage in ("new", "summarized", "recommended", "stale", "archived", "ignored"):
            stages[stage] = len(self.db.get_items_by_stage(stage))

        paused_text = " (已暂停推送)" if self.is_paused() else ""
        return (
            f"系统状态{paused_text}：\n"
            f"  待处理：{stages['new'] + stages['summarized']}\n"
            f"  今日推荐：{stages['recommended']}\n"
            f"  已过期推荐：{stages['stale']}\n"
            f"  已归档：{stages['archived']}\n"
            f"  已忽略：{stages['ignored']}"
        )

    async def _cmd_pause(self) -> str:
        self.db.set_paused(True)
        return "已暂停每日推送。发送「恢复」重新启用。"

    async def _cmd_resume(self) -> str:
        self.db.set_paused(False)
        return "已恢复每日推送。"

    async def _cmd_push(self) -> str:
        return "手动推送请在终端运行：passive-agent daily"

    async def _cmd_detail(self, text: str) -> str:
        _, _, rest = text.partition("详情")
        parts = rest.strip().split()
        item_id = parts[0] if parts else ""
        if not item_id:
            return "请提供条目 ID，例如：详情 item_20260523_001"

        item = self.db.get_item(item_id)
        if not item:
            return f"未找到条目：{item_id}"

        enriched = Ranker(self.db).enrich([item])[0]
        score = f"{item.priority_score:.1f}" if item.priority_score is not None else "未评分"
        topics = ", ".join(item.topics) if item.topics else "无"
        related_stars = ", ".join(enriched.related_stars) if enriched.related_stars else "无"
        related_zotero = ", ".join(enriched.related_zotero) if enriched.related_zotero else "无"

        return (
            f"条目详情：{item.id}\n"
            f"- 标题：{item.title}\n"
            f"- 来源：{item.source}\n"
            f"- 评分：{score}\n"
            f"- 摘要：{item.summary or '无'}\n"
            f"- 面试价值：{item.interview_relevance or '无'}\n"
            f"- Topics：{topics}\n"
            f"- 建议动作：{item.recommended_action or '无'}\n"
            f"- 预计时间：{item.estimated_minutes if item.estimated_minutes is not None else '未知'} 分钟\n"
            f"- 链接：{item.url or item.local_path or '无'}\n"
            f"- 相关 GitHub Stars：{related_stars}\n"
            f"- 相关 Zotero：{related_zotero}"
        )
