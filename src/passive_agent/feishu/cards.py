from __future__ import annotations

import json
from datetime import date

from passive_agent.storage.models import EnrichedItem


class CardBuilder:
    """构建飞书卡片 JSON"""

    @staticmethod
    def build_daily_card(items: list[EnrichedItem]) -> dict:
        elements = []

        for i, enriched in enumerate(items, 1):
            item = enriched.item

            # 条目信息
            source_text = {"zotero": "Zotero", "obsidian_inbox": "Obsidian", "github_star": "GitHub"}
            source_label = source_text.get(item.source, item.source)
            topic_label = " · ".join(item.topics[:2]) if item.topics else ""

            elements.append({
                "tag": "markdown",
                "content": (
                    f"**{i}. {item.title}**\n"
                    f"来源：{source_label}"
                    f"{' · ' + topic_label if topic_label else ''}"
                    f" · 预计 {item.estimated_minutes or '?'} 分钟\n"
                    f"面试价值：{item.interview_relevance or '待分析'}"
                ),
            })

            # 相关 star 提示
            if enriched.related_stars:
                stars_text = ", ".join(enriched.related_stars[:3])
                elements.append({
                    "tag": "markdown",
                    "content": f"相关：你 star 过 {stars_text}",
                })

            # 操作按钮
            elements.append({
                "tag": "action",
                "actions": [
                    _button("展开", "primary", {"action": "expand", "item_id": item.id}),
                    _button("面试卡", "primary", {"action": "card", "item_id": item.id}),
                    _button("周末", "default", {"action": "weekend", "item_id": item.id}),
                    _button("忽略", "danger", {"action": "ignore", "item_id": item.id}),
                ],
            })

            if i < len(items):
                elements.append({"tag": "hr"})

        # 相关旧文章提示
        all_related = []
        for e in items:
            all_related.extend(e.related_zotero[:1])
        if all_related:
            elements.append({"tag": "hr"})
            related_text = "\n".join(f"· {t}" for t in all_related[:3])
            elements.append({
                "tag": "markdown",
                "content": f"**Zotero 中可能相关的旧文章：**\n{related_text}",
            })

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"今日推荐 · {date.today().strftime('%m月%d日')}"},
                "template": "blue",
            },
            "elements": elements,
        }

    @staticmethod
    def build_expand_card(item, detail: str) -> dict:
        elements = [
            {
                "tag": "markdown",
                "content": detail,
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": (
                    f"**原文位置：**\n"
                    f"{'· ' + item.url if item.url else '· 本地 Zotero 中搜索标题定位'}"
                ),
            },
            {
                "tag": "action",
                "actions": [
                    _button("生成面试卡", "primary", {"action": "card", "item_id": item.id}),
                    _button("生成技术笔记", "primary", {"action": "note", "item_id": item.id}),
                    _button("标记已读", "default", {"action": "read", "item_id": item.id}),
                ],
            },
        ]

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"展开：{item.title[:30]}"},
                "template": "green",
            },
            "elements": elements,
        }

    @staticmethod
    def build_result_card(title: str, message: str, success: bool = True) -> dict:
        template = "green" if success else "red"
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": [{"tag": "markdown", "content": message}],
        }


def _button(text: str, btn_type: str, value: dict) -> dict:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": btn_type,
        "value": value,
    }
