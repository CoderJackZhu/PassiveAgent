import os

import click

from passive_agent.pipeline import DailyPipeline
from passive_agent.storage.database import Database
from passive_agent.utils.config import load_config
from passive_agent.utils.logger import log


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
    feishu_bot = None
    if os.environ.get("FEISHU_APP_ID") and os.environ.get("FEISHU_APP_SECRET"):
        try:
            from passive_agent.feishu.bot import FeishuBot
            feishu_bot = FeishuBot(config, db, llm)
        except Exception as e:
            log.warning(f"Feishu Bot init failed (push disabled): {e}")

    try:
        pipeline = DailyPipeline(config, db, llm, feishu_bot=feishu_bot)
        result = asyncio.run(pipeline.run())

        if result.status == "empty":
            log.info("No new items to process today.")
        elif result.status == "all_duplicates":
            log.info(f"Collected {result.collected} items, all duplicates.")
        elif result.status == "success":
            log.info(f"Done. Collected {result.collected}, processed {result.processed}, "
                     f"recommended {len(result.recommended)} items.")
        elif result.status == "error":
            log.error(f"Pipeline failed: {result.errors}")
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

        click.echo("Passive Agent Status:")
        click.echo(f"  New:         {new_count}")
        click.echo(f"  Summarized:  {summarized_count}")
        click.echo(f"  Recommended: {recommended_count}")
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

    try:
        from passive_agent.feishu.bot import FeishuBot
        bot = FeishuBot(config, db, llm)
        bot.start()
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("Set FEISHU_APP_ID and FEISHU_APP_SECRET environment variables.")
        raise SystemExit(1)
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
              type=click.Choice(["card", "note", "ignore", "read", "link", "mute"]),
              help="执行的操作类型")
@click.pass_context
def action(ctx, item_id: str, action_type: str):
    """对条目执行操作 (生成面试卡/笔记/忽略/标记已读/关联笔记/少推类似)"""
    import asyncio

    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        from passive_agent.actions.base import ActionResult
        from passive_agent.integrations.obsidian_writer import ObsidianWriter

        writer = ObsidianWriter(config.sources.obsidian.vault_path)

        if action_type in ("card", "note"):
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                click.echo("Error: DEEPSEEK_API_KEY not set", err=True)
                raise SystemExit(1)

            from passive_agent.integrations.deepseek import DeepSeekClient
            llm = DeepSeekClient(api_key=api_key)

            if action_type == "card":
                from passive_agent.actions.interview_card import InterviewCardAction
                handler = InterviewCardAction(db, llm, writer, config.goals)
            else:
                from passive_agent.actions.tech_note import TechNoteAction
                handler = TechNoteAction(db, llm, writer, config.goals)
        elif action_type == "ignore":
            from passive_agent.actions.ignore import IgnoreAction
            handler = IgnoreAction(db, config.scoring.negative_feedback)
        elif action_type == "link":
            from passive_agent.actions.link_notes import LinkNotesAction
            handler = LinkNotesAction(db, writer)
        elif action_type == "mute":
            from passive_agent.actions.mute_similar import MuteSimilarAction
            handler = MuteSimilarAction(db, config.scoring.negative_feedback)
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

        feishu_bot = None
        if os.environ.get("FEISHU_APP_ID") and os.environ.get("FEISHU_APP_SECRET"):
            from passive_agent.feishu.bot import FeishuBot
            feishu_bot = FeishuBot(config, db)

        if not feishu_bot:
            click.echo("Error: Feishu Bot not configured", err=True)
            raise SystemExit(1)

        from passive_agent.storage.models import EnrichedItem
        enriched = [EnrichedItem(item=item, related_zotero=[], related_stars=[]) for item in items]
        feishu_bot.send_weekend_card(enriched)
        click.echo(f"已推送 {len(items)} 条周末阅读材料。")
    finally:
        db.close()


@cli.command("init-stars")
@click.option("--max-pages", default=10, help="最多获取的页数 (每页100个)")
@click.pass_context
def init_stars(ctx, max_pages: int):
    """一次性导入 GitHub Stars 并分类"""
    import asyncio

    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        click.echo("Error: GITHUB_TOKEN not set", err=True)
        raise SystemExit(1)

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        click.echo("Error: DEEPSEEK_API_KEY not set", err=True)
        raise SystemExit(1)

    try:
        from passive_agent.collectors.github_stars import GitHubStarsInitializer
        from passive_agent.integrations.deepseek import DeepSeekClient

        llm = DeepSeekClient(api_key=api_key)
        initializer = GitHubStarsInitializer(token, db, llm)
        count = asyncio.run(initializer.run(max_pages=max_pages))
        click.echo(f"Done. Imported {count} relevant repos from GitHub Stars.")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
