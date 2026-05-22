import os

import click

from passive_agent.pipeline import DailyPipeline
from passive_agent.storage.database import Database
from passive_agent.utils.config import load_config
from passive_agent.utils.logger import log


def _missing_env(names: list[str]) -> list[str]:
    return [name for name in names if not os.environ.get(name)]


def _init_feishu_bot(config, db, llm=None, *, require_chat_id: bool = False):
    required = ["FEISHU_APP_ID", "FEISHU_APP_SECRET"]
    if require_chat_id:
        required.append("FEISHU_CHAT_ID")

    missing = _missing_env(required)
    if missing:
        log.warning(f"Feishu disabled, missing env: {', '.join(missing)}")
        return None

    try:
        from passive_agent.feishu.bot import FeishuBot
        return FeishuBot(config, db, llm)
    except Exception as e:
        log.warning(f"Feishu Bot init failed (push disabled): {e}")
        return None


def _notify_daily_error(feishu_bot, result):
    if not feishu_bot or result.status == "paused":
        return
    if result.status != "error" and not result.errors:
        return

    error_text = "; ".join(result.errors) if result.errors else f"Pipeline status: {result.status}"
    try:
        feishu_bot.send_error_notification(error_text)
    except Exception as e:
        log.warning(f"Feishu error notification failed: {e}")


@click.group()
@click.option("--config-dir", default="config", help="配置文件目录")
@click.pass_context
def cli(ctx, config_dir: str):
    """Passive Agent Workbench — 注意力调度系统"""
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = config_dir


@cli.command()
@click.pass_context
def daily(ctx):
    """运行每日处理流水线"""
    import asyncio

    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    llm = None
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if api_key:
        from passive_agent.integrations.deepseek import DeepSeekClient
        llm = DeepSeekClient(api_key=api_key)
    else:
        log.warning("DEEPSEEK_API_KEY not set, running without LLM (collect only)")

    # 飞书推送（可选）
    feishu_bot = _init_feishu_bot(config, db, llm, require_chat_id=True)

    try:
        pipeline = DailyPipeline(config, db, llm, feishu_bot=feishu_bot)
        result = asyncio.run(pipeline.run())

        if result.status == "empty":
            log.info("No new items to process today.")
        elif result.status == "all_duplicates":
            log.info(f"Collected {result.collected} items, all duplicates.")
        elif result.status == "paused":
            log.info("Daily pipeline paused; collection and push skipped.")
        elif result.status == "success":
            log.info(f"Done. Collected {result.collected}, processed {result.processed}, "
                     f"recommended {len(result.recommended)} items, pushed {result.pushed}.")
        elif result.status == "error":
            log.error(f"Pipeline failed: {result.errors}")

        _notify_daily_error(feishu_bot, result)
    finally:
        db.close()


@cli.command("init-db")
@click.pass_context
def init_db(ctx):
    """初始化数据库"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()
    db.close()
    click.echo(f"Database initialized at {config.db_path}")


@cli.command("weekly-report")
@click.pass_context
def weekly_report(ctx):
    """生成本周周报"""
    from passive_agent.pipeline import generate_weekly_report

    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        path = generate_weekly_report(config, db)
        click.echo(f"Weekly report: {path}")
    finally:
        db.close()


@cli.command()
@click.pass_context
def status(ctx):
    """显示系统状态"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        new_count = len(db.get_items_by_stage("new"))
        summarized_count = len(db.get_items_by_stage("summarized"))
        recommended_count = len(db.get_items_by_stage("recommended"))
        archived_count = len(db.get_items_by_stage("archived"))
        ignored_count = len(db.get_items_by_stage("ignored"))
        stale_count = len(db.get_items_by_stage("stale"))

        click.echo("Passive Agent Status:")
        click.echo(f"  New:         {new_count}")
        click.echo(f"  Summarized:  {summarized_count}")
        click.echo(f"  Recommended: {recommended_count}")
        click.echo(f"  Stale:       {stale_count}")
        click.echo(f"  Archived:    {archived_count}")
        click.echo(f"  Ignored:     {ignored_count}")
    finally:
        db.close()


@cli.command()
@click.pass_context
def serve(ctx):
    """启动飞书 Bot 常驻服务（长连接模式）"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        click.echo("Error: DEEPSEEK_API_KEY not set", err=True)
        raise SystemExit(1)

    from passive_agent.integrations.deepseek import DeepSeekClient
    llm = DeepSeekClient(api_key=api_key)

    missing = _missing_env(["FEISHU_APP_ID", "FEISHU_APP_SECRET"])
    if missing:
        click.echo(f"Error: missing env: {', '.join(missing)}", err=True)
        click.echo("Set FEISHU_APP_ID and FEISHU_APP_SECRET environment variables.")
        raise SystemExit(1)

    try:
        from passive_agent.feishu.bot import FeishuBot
        bot = FeishuBot(config, db, llm)
        bot.start()
    except KeyboardInterrupt:
        log.info("Bot stopped.")
    finally:
        db.close()


@cli.command("list")
@click.option("--stage", default="recommended", help="筛选 stage")
@click.option("--limit", default=10, help="显示条数")
@click.pass_context
def list_items(ctx, stage: str, limit: int):
    """列出条目"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        items = db.get_items_by_stage(stage)[:limit]
        if not items:
            click.echo(f"No items with stage '{stage}'")
            return

        for item in items:
            score = f"[{item.priority_score:.1f}]" if item.priority_score else "[--]"
            click.echo(f"  {score} {item.id}  {item.title[:50]}")
    finally:
        db.close()


@cli.command()
@click.argument("item_id")
@click.option("--type", "action_type", required=True,
              type=click.Choice(["card", "note", "ignore", "read", "link", "mute", "weekend"]),
              help="执行的操作类型")
@click.pass_context
def action(ctx, item_id: str, action_type: str):
    """对条目执行操作 (生成面试卡/笔记/忽略/标记已读/关联笔记/少推类似/加入周末)"""
    import asyncio

    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        from passive_agent.actions.base import ActionResult
        from passive_agent.integrations.obsidian_writer import ObsidianWriter

        writer = ObsidianWriter(config.sources.obsidian.vault_path)
        prompts_dir = os.path.join(config.project_root, config.prompts_dir) if config.project_root else config.prompts_dir

        if action_type in ("card", "note"):
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                click.echo("Error: DEEPSEEK_API_KEY not set", err=True)
                raise SystemExit(1)

            from passive_agent.integrations.deepseek import DeepSeekClient
            llm = DeepSeekClient(api_key=api_key)

            if action_type == "card":
                from passive_agent.actions.interview_card import InterviewCardAction
                handler = InterviewCardAction(db, llm, writer, config.goals, prompts_dir)
            else:
                from passive_agent.actions.tech_note import TechNoteAction
                handler = TechNoteAction(db, llm, writer, config.goals, prompts_dir)
        elif action_type == "ignore":
            from passive_agent.actions.ignore import IgnoreAction
            handler = IgnoreAction(db, config.scoring.negative_feedback)
        elif action_type == "link":
            from passive_agent.actions.link_notes import LinkNotesAction
            handler = LinkNotesAction(db, writer, config.sources.obsidian.read_paths)
        elif action_type == "mute":
            from passive_agent.actions.mute_similar import MuteSimilarAction
            handler = MuteSimilarAction(db, config.scoring.negative_feedback)
        elif action_type == "weekend":
            item = db.get_item(item_id)
            if not item:
                click.echo(f"✗ Item not found: {item_id}", err=True)
                raise SystemExit(1)
            current_queue = db.get_weekend_queue()
            if len(current_queue) >= config.scoring.weekend_limit:
                click.echo(f"✗ 周末队列已满 ({config.scoring.weekend_limit} 条)", err=True)
                raise SystemExit(1)
            db.conn.execute("UPDATE items SET is_weekend = 1 WHERE id = ?", (item_id,))
            db.conn.commit()
            click.echo(f"✓ 已加入周末队列: {item.title}")
            return
        else:  # read
            from passive_agent.actions.mark_read import MarkReadAction
            handler = MarkReadAction(db, writer)

        result: ActionResult = asyncio.run(handler.execute(item_id))

        if result.success:
            click.echo(f"✓ {result.message}")
            if result.output_path:
                click.echo(f"  → {result.output_path}")
        else:
            click.echo(f"✗ {result.message}", err=True)
            raise SystemExit(1)
    finally:
        db.close()


@cli.command("weekend-push")
@click.pass_context
def weekend_push(ctx):
    """推送周末队列到飞书"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        items = db.get_weekend_queue()
        if not items:
            click.echo("周末队列为空，无需推送。")
            return

        feishu_bot = _init_feishu_bot(config, db, require_chat_id=True)

        if not feishu_bot:
            click.echo("Error: Feishu Bot not configured", err=True)
            raise SystemExit(1)

        from passive_agent.storage.models import EnrichedItem
        enriched = [EnrichedItem(item=item, related_zotero=[], related_stars=[]) for item in items]
        if not feishu_bot.send_weekend_card(enriched):
            click.echo("Error: Feishu weekend push failed", err=True)
            raise SystemExit(1)
        click.echo(f"已推送 {len(items)} 条周末阅读材料。")
    finally:
        db.close()


@cli.command("feishu-push")
@click.option("--stage", default="recommended", help="推送指定 stage 的条目")
@click.option("--limit", default=5, help="最多推送条数")
@click.pass_context
def feishu_push(ctx, stage: str, limit: int):
    """手动推送当前条目到飞书，用于验证飞书配置"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        items = db.get_items_by_stage(stage)[:limit]
        if not items:
            click.echo(f"No items with stage '{stage}'")
            return

        feishu_bot = _init_feishu_bot(config, db, require_chat_id=True)
        if not feishu_bot:
            click.echo("Error: Feishu Bot not configured", err=True)
            raise SystemExit(1)

        from passive_agent.storage.models import EnrichedItem
        enriched = [EnrichedItem(item=item, related_zotero=[], related_stars=[]) for item in items]
        if not feishu_bot.send_daily_card(enriched, respect_pause=False):
            click.echo("Error: Feishu push failed", err=True)
            raise SystemExit(1)

        click.echo(f"已推送 {len(items)} 条 {stage} 条目。")
    finally:
        db.close()


@cli.command("init-stars")
@click.option("--max-pages", default=10, help="最多获取的页数 (每页100个)")
@click.option("--refresh", is_flag=True, default=False, help="仅刷新已有条目的元数据(star数/语言)")
@click.pass_context
def init_stars(ctx, max_pages: int, refresh: bool):
    """一次性导入 GitHub Stars 并分类"""
    import asyncio

    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        click.echo("Error: GITHUB_TOKEN not set", err=True)
        raise SystemExit(1)

    try:
        from passive_agent.collectors.github_stars import GitHubStarsInitializer
        from passive_agent.integrations.deepseek import DeepSeekClient

        if refresh:
            initializer = GitHubStarsInitializer(token, db, None)
            count = asyncio.run(initializer.refresh_metadata(max_pages=max_pages))
            click.echo(f"Done. Refreshed metadata for {count} items.")
        else:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                click.echo("Error: DEEPSEEK_API_KEY not set", err=True)
                raise SystemExit(1)
            llm = DeepSeekClient(api_key=api_key)
            initializer = GitHubStarsInitializer(token, db, llm)
            count = asyncio.run(initializer.run(max_pages=max_pages))
            click.echo(f"Done. Imported {count} relevant repos from GitHub Stars.")
    finally:
        db.close()


@cli.command("list-stars")
@click.option("--topic", default=None, help="按 topic 过滤 (如 Agent, RAG, LLM)")
@click.option("--language", "lang", default=None, help="按语言过滤 (如 Python, TypeScript)")
@click.option("--sort", "sort_by", default="stars", type=click.Choice(["stars", "name", "date"]),
              help="排序方式")
@click.option("--limit", default=50, help="显示条数")
@click.pass_context
def list_stars(ctx, topic: str | None, lang: str | None, sort_by: str, limit: int):
    """查看已导入的 GitHub Stars（支持筛选/排序）"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        items = db.get_items_by_source("github_star", topic=topic)

        if lang:
            lang_lower = lang.lower()
            items = [i for i in items if (i.extra_meta or {}).get("language", "").lower() == lang_lower]

        if sort_by == "stars":
            items.sort(key=lambda i: (i.extra_meta or {}).get("stars", 0), reverse=True)
        elif sort_by == "name":
            items.sort(key=lambda i: i.title.lower())
        else:
            items.sort(key=lambda i: i.collected_at, reverse=True)

        items = items[:limit]

        if not items:
            click.echo("No GitHub Stars found matching the criteria.")
            return

        click.echo(f"{'Stars':<8}{'Language':<13}{'Topics':<20}{'Repo':<40}URL")
        click.echo("-" * 110)
        for item in items:
            meta = item.extra_meta or {}
            stars = meta.get("stars", 0)
            stars_str = f"{stars/1000:.1f}k" if stars >= 1000 else str(stars)
            language = meta.get("language", "-")[:12]
            topics_str = ",".join(item.topics[:3])[:19]
            title = item.title[:39]
            click.echo(f"{stars_str:<8}{language:<13}{topics_str:<20}{title:<40}{item.url or ''}")

        click.echo(f"\nTotal: {len(items)} repos")
    finally:
        db.close()


@cli.command("export-stars")
@click.option("--output", default=None, help="输出文件路径 (默认 data/reports/github_stars.md)")
@click.option("--topic", default=None, help="只导出某个 topic")
@click.pass_context
def export_stars(ctx, output: str | None, topic: str | None):
    """导出 GitHub Stars 为 Markdown 分类文件"""
    from collections import defaultdict

    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        items = db.get_items_by_source("github_star", topic=topic)
        if not items:
            click.echo("No GitHub Stars found.")
            return

        grouped: dict[str, list] = defaultdict(list)
        for item in items:
            for t in item.topics:
                grouped[t].append(item)

        lines = ["# GitHub Stars 分类整理\n"]
        for group_topic in sorted(grouped.keys()):
            group_items = grouped[group_topic]
            group_items.sort(key=lambda i: (i.extra_meta or {}).get("stars", 0), reverse=True)
            lines.append(f"\n## {group_topic}\n")
            lines.append("| Stars | Repo | Language | Description |")
            lines.append("|-------|------|----------|-------------|")
            for item in group_items:
                meta = item.extra_meta or {}
                stars = meta.get("stars", 0)
                stars_str = f"{stars/1000:.1f}k" if stars >= 1000 else str(stars)
                language = meta.get("language", "-")
                desc = (item.raw_text or "")[:80].replace("|", "/")
                lines.append(f"| {stars_str} | [{item.title}]({item.url}) | {language} | {desc} |")

        out_path = output or os.path.join(config.project_root or ".", "data", "reports", "github_stars.md")
        from pathlib import Path
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        click.echo(f"Exported {len(items)} repos to {out_path}")
    finally:
        db.close()


@cli.command("zotero-writeback")
@click.option("--execute", is_flag=True, default=False,
              help="正式执行写入（默认 dry-run 仅打印）")
@click.pass_context
def zotero_writeback(ctx, execute: bool):
    """测试/执行 Zotero tag 回写（默认 dry-run）"""
    import asyncio

    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        from passive_agent.integrations.zotero_writeback import ZoteroWriteBack

        if not ZoteroWriteBack.is_available():
            click.echo("Error: Zotero local API not available (is Zotero running with HTTP API enabled?)", err=True)
            raise SystemExit(1)

        dry_run = not execute
        if dry_run:
            click.echo("Running in DRY-RUN mode (use --execute to write for real)")
        else:
            click.echo("⚠ EXECUTE mode: will modify Zotero item tags!")

        wb = ZoteroWriteBack(db, dry_run=dry_run)
        count = asyncio.run(wb.flush_queue())

        if execute:
            click.echo(f"Done. {count} tags written to Zotero.")
        else:
            click.echo("Dry-run complete. No changes made.")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
