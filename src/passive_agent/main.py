from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from datetime import date
import html
import os
import re
import webbrowser

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


def _build_llm(config, *, required: bool = False):
    if config.llm.provider != "deepseek":
        message = f"LLM provider '{config.llm.provider}' is not supported"
        if required:
            raise click.ClickException(message)
        log.warning(f"{message}, running without LLM")
        return None

    api_key = os.environ.get(config.llm.api_key_env)
    if not api_key:
        message = f"{config.llm.api_key_env} not set"
        if required:
            raise click.ClickException(message)
        log.warning(f"{message}, running without LLM (collect only)")
        return None

    from passive_agent.integrations.deepseek import DeepSeekClient
    return DeepSeekClient(
        api_key=api_key,
        api_key_env=config.llm.api_key_env,
        base_url=config.llm.base_url,
        model=config.llm.model,
        temperature=config.llm.temperature,
        max_concurrency=config.llm.max_concurrency,
        max_retries=config.llm.max_retries,
        retry_backoff_base_seconds=config.llm.retry_backoff_base_seconds,
    )


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


STAGE_ROWS = (
    ("New", "new", "cyan"),
    ("Summarized", "summarized", "blue"),
    ("Recommended", "recommended", "green"),
    ("Stale", "stale", "yellow"),
    ("Archived", "archived", "magenta"),
    ("Ignored", "ignored", "red"),
)


def _latest_collection_date(db: Database) -> str:
    row = db.conn.execute("SELECT date FROM daily_log ORDER BY date DESC LIMIT 1").fetchone()
    return row["date"] if row else date.today().isoformat()


def _count_source_items_on(db: Database, source: str, date_str: str) -> int:
    row = db.conn.execute(
        "SELECT COUNT(*) AS cnt FROM items WHERE source = ? AND substr(collected_at, 1, 10) = ?",
        (source, date_str),
    ).fetchone()
    return int(row["cnt"]) if row else 0


def _collector_health_rows(config, db: Database) -> list[dict]:
    collection_date = _latest_collection_date(db)
    zotero_path = Path(config.sources.zotero.db_path).expanduser()
    obsidian_path = Path(config.sources.obsidian.inbox_path).expanduser()

    return [
        {
            "name": "Zotero",
            "enabled": config.sources.zotero.enabled,
            "available": zotero_path.exists(),
            "date": collection_date,
            "count": _count_source_items_on(db, "zotero", collection_date),
        },
        {
            "name": "Obsidian",
            "enabled": config.sources.obsidian.enabled,
            "available": obsidian_path.exists() and obsidian_path.is_file(),
            "date": collection_date,
            "count": _count_source_items_on(db, "obsidian_inbox", collection_date),
        },
        {
            "name": "GitHub Stars",
            "enabled": config.sources.github_stars.enabled,
            "available": bool(os.environ.get("GITHUB_TOKEN")),
            "date": collection_date,
            "count": _count_source_items_on(db, "github_star", collection_date),
        },
        {
            "name": "HF Daily Papers",
            "enabled": config.sources.hf_daily.enabled,
            "available": True,
            "date": collection_date,
            "count": _count_source_items_on(db, "hf_daily_papers", collection_date),
        },
    ]


def _format_feedback_summary(db: Database, limit: int = 5) -> str:
    limit = max(0, limit)
    total_row = db.conn.execute("SELECT COUNT(*) AS cnt FROM feedback").fetchone()
    total = int(total_row["cnt"]) if total_row else 0
    if total == 0:
        return "No feedback recorded"

    action_rows = db.conn.execute(
        "SELECT action, COUNT(*) AS cnt FROM feedback GROUP BY action ORDER BY cnt DESC, action"
    ).fetchall()
    actions = ", ".join(f"{r['action']}={r['cnt']}" for r in action_rows)

    topic_rows = db.conn.execute(
        "SELECT topic, weight FROM topic_weights WHERE weight < 1.0 ORDER BY weight ASC, topic LIMIT ?",
        (limit,),
    ).fetchall()
    lowered_topics = ", ".join(f"{r['topic']}={r['weight']:.2f}" for r in topic_rows)

    source_rows = db.conn.execute(
        "SELECT source, weight FROM source_weights WHERE weight < 1.0 ORDER BY weight ASC, source LIMIT ?",
        (limit,),
    ).fetchall()
    lowered_sources = ", ".join(f"{r['source']}={r['weight']:.2f}" for r in source_rows)

    parts = [f"{total} feedback records"]
    if actions:
        parts.append(f"actions: {actions}")
    if lowered_topics:
        parts.append(f"lowered topics: {lowered_topics}")
    if lowered_sources:
        parts.append(f"lowered sources: {lowered_sources}")
    return "; ".join(parts)


def _render_inline_markdown(text: str) -> str:
    parts = []
    pos = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", text):
        parts.append(_render_inline_without_links(text[pos:match.start()]))
        label = _render_inline_without_links(match.group(1))
        href = html.escape(match.group(2), quote=True)
        parts.append(f'<a href="{href}">{label}</a>')
        pos = match.end()
    parts.append(_render_inline_without_links(text[pos:]))
    return "".join(parts)


def _render_inline_without_links(text: str) -> str:
    escaped = html.escape(text, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _markdown_to_html(markdown_text: str, title: str) -> str:
    body_lines: list[str] = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            body_lines.append("</ul>")
            in_list = False

    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped:
            close_list()
            continue

        if stripped == "---":
            close_list()
            body_lines.append("<hr>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            body_lines.append(f"<h{level}>{_render_inline_markdown(heading.group(2))}</h{level}>")
            continue

        if stripped.startswith("- "):
            if not in_list:
                body_lines.append("<ul>")
                in_list = True
            body_lines.append(f"<li>{_render_inline_markdown(stripped[2:])}</li>")
            continue

        close_list()
        body_lines.append(f"<p>{_render_inline_markdown(stripped)}</p>")

    close_list()
    escaped_title = html.escape(title)
    body = "\n".join(body_lines)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f7f7f4;
      --fg: #1f2933;
      --muted: #5f6b76;
      --panel: #ffffff;
      --border: #d8ddd8;
      --link: #2563eb;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #101214;
        --fg: #e5e7eb;
        --muted: #a3adb8;
        --panel: #171a1f;
        --border: #2f363d;
        --link: #8ab4ff;
      }}
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 860px;
      margin: 0 auto;
      padding: 48px 24px 72px;
    }}
    h1, h2, h3 {{
      line-height: 1.25;
      margin: 1.6em 0 0.5em;
    }}
    h1 {{ margin-top: 0; font-size: 2rem; }}
    p, ul {{ margin: 0.75rem 0; }}
    ul {{ padding-left: 1.4rem; }}
    li {{ margin: 0.3rem 0; }}
    a {{ color: var(--link); }}
    strong {{ color: var(--fg); }}
    hr {{ border: 0; border-top: 1px solid var(--border); margin: 2rem 0; }}
    main {{
      background: var(--panel);
      border-left: 1px solid var(--border);
      border-right: 1px solid var(--border);
      min-height: 100vh;
    }}
    @media (max-width: 720px) {{
      main {{
        padding: 32px 18px 56px;
        border: 0;
      }}
    }}
  </style>
</head>
<body>
  <main>
{body}
  </main>
</body>
</html>
"""


def _report_title(markdown_text: str, fallback: str) -> str:
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _write_report_html(markdown_path: Path) -> Path:
    markdown_text = markdown_path.read_text(encoding="utf-8")
    title = _report_title(markdown_text, markdown_path.stem)
    html_path = markdown_path.with_suffix(".html")
    html_path.write_text(_markdown_to_html(markdown_text, title), encoding="utf-8")
    return html_path


def _open_latest_report(config, prefix: str, label: str) -> Path:
    reports_dir = Path(config.reports_dir)
    candidates = sorted(
        reports_dir.glob(f"{prefix}_*.md"),
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    if not candidates:
        raise click.ClickException(f"No {label} report found in {reports_dir}")

    html_path = _write_report_html(candidates[0])
    webbrowser.open(html_path.resolve().as_uri())
    return html_path


def _echo_dashboard_plain(config, db: Database):
    counts = db.count_items_by_stage()
    dashboard_limit = max(0, config.display.dashboard_limit)
    click.echo("Stage counts")
    for label, stage, _color in STAGE_ROWS:
        click.echo(f"  {label}: {counts.get(stage, 0)}")

    click.echo("\nToday's recommendations")
    recommended = db.get_items_by_stage("recommended")
    recommended.sort(key=lambda item: (item.priority_score or 0, item.created_at), reverse=True)
    if recommended and dashboard_limit:
        for item in recommended[:dashboard_limit]:
            score = f"{item.priority_score:.1f}" if item.priority_score is not None else "-"
            topics = ", ".join(item.topics) or "-"
            minutes = item.estimated_minutes if item.estimated_minutes is not None else "-"
            action = item.recommended_action or "-"
            click.echo(f"  {score} | {item.title} | {item.source} | {topics} | {minutes} | {action}")
    else:
        click.echo("  No recommendations")

    click.echo("\nSource health")
    for row in _collector_health_rows(config, db):
        enabled = "yes" if row["enabled"] else "no"
        available = "yes" if row["available"] else "no"
        click.echo(
            f"  {row['name']}: enabled={enabled}, available={available}, "
            f"last_date={row['date']}, last_count={row['count']}"
        )

    pause_text = "Paused" if db.is_paused() else "Active"
    click.echo("\nPause status")
    click.echo(f"  Pause status: {pause_text}")
    click.echo(f"  Feedback summary: {_format_feedback_summary(db, config.display.feedback_summary_limit)}")


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

    llm = _build_llm(config)

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
def dashboard(ctx):
    """显示 Rich 终端看板"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table
        except ImportError:
            _echo_dashboard_plain(config, db)
            return

        console = Console()
        counts = db.count_items_by_stage()
        dashboard_limit = max(0, config.display.dashboard_limit)
        stage_table = Table(title="Stage counts", show_header=True, header_style="bold")
        stage_table.add_column("Stage")
        stage_table.add_column("Count", justify="right")
        for label, stage, color in STAGE_ROWS:
            count = counts.get(stage, 0)
            stage_table.add_row(f"[{color}]{label}[/{color}]", f"[bold {color}]{count}[/bold {color}]")
        console.print(stage_table)

        rec_table = Table(title="Today's recommendations", show_header=True, header_style="bold")
        rec_table.add_column("Score", justify="right")
        rec_table.add_column("Title")
        rec_table.add_column("Source")
        rec_table.add_column("Topics")
        rec_table.add_column("Minutes", justify="right")
        rec_table.add_column("Action")
        recommended = db.get_items_by_stage("recommended")
        recommended.sort(key=lambda item: (item.priority_score or 0, item.created_at), reverse=True)
        if recommended and dashboard_limit:
            for item in recommended[:dashboard_limit]:
                score = f"{item.priority_score:.1f}" if item.priority_score is not None else "-"
                rec_table.add_row(
                    score,
                    item.title,
                    item.source,
                    ", ".join(item.topics) or "-",
                    str(item.estimated_minutes) if item.estimated_minutes is not None else "-",
                    item.recommended_action or "-",
                )
        else:
            rec_table.add_row("-", "No recommendations", "-", "-", "-", "-")
        console.print(rec_table)

        health_table = Table(title="Source health", show_header=True, header_style="bold")
        health_table.add_column("Collector")
        health_table.add_column("Enabled")
        health_table.add_column("Available")
        health_table.add_column("Last date")
        health_table.add_column("Last count", justify="right")
        for row in _collector_health_rows(config, db):
            enabled = "[green]yes[/green]" if row["enabled"] else "[red]no[/red]"
            available = "[green]yes[/green]" if row["available"] else "[red]no[/red]"
            health_table.add_row(row["name"], enabled, available, row["date"], str(row["count"]))
        console.print(health_table)

        paused = db.is_paused()
        pause_text = "Paused" if paused else "Active"
        body = (
            f"Pause status: {pause_text}\n"
            f"Feedback summary: {_format_feedback_summary(db, config.display.feedback_summary_limit)}"
        )
        console.print(Panel(body, title="Pause status", expand=False))
    finally:
        db.close()


@cli.command("open-daily")
@click.pass_context
def open_daily(ctx):
    """将最新日报渲染为 HTML 并在浏览器中打开"""
    config = load_config(ctx.obj["config_dir"])
    html_path = _open_latest_report(config, "daily_review", "daily")
    click.echo(f"Opened {html_path}")


@cli.command("open-weekly")
@click.pass_context
def open_weekly(ctx):
    """将最新周报渲染为 HTML 并在浏览器中打开"""
    config = load_config(ctx.obj["config_dir"])
    html_path = _open_latest_report(config, "weekly_review", "weekly")
    click.echo(f"Opened {html_path}")


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

    try:
        llm = _build_llm(config, required=True)

        missing = _missing_env(["FEISHU_APP_ID", "FEISHU_APP_SECRET"])
        if missing:
            click.echo(f"Error: missing env: {', '.join(missing)}", err=True)
            click.echo("Set FEISHU_APP_ID and FEISHU_APP_SECRET environment variables.")
            raise SystemExit(1)

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
            llm = _build_llm(config, required=True)

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
@click.option("--limit", type=int, default=None, help="最多推送条数")
@click.pass_context
def feishu_push(ctx, stage: str, limit: int | None):
    """手动推送当前条目到飞书，用于验证飞书配置"""
    config = load_config(ctx.obj["config_dir"])
    db = Database(config.db_path)
    db.initialize()

    try:
        limit = max(0, config.display.manual_push_limit if limit is None else limit)
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
@click.option("--max-pages", type=int, default=None, help="最多获取的页数")
@click.option("--refresh", is_flag=True, default=False, help="仅刷新已有条目的元数据(star数/语言)")
@click.pass_context
def init_stars(ctx, max_pages: int | None, refresh: bool):
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
        stars_config = config.sources.github_stars
        max_pages = max_pages if max_pages is not None else stars_config.max_pages

        if refresh:
            initializer = GitHubStarsInitializer(
                token,
                db,
                None,
                max_pages=max_pages,
                per_page=stars_config.per_page,
                classification_batch_size=stars_config.classification_batch_size,
                http_timeout_seconds=stars_config.http_timeout_seconds,
            )
            count = asyncio.run(initializer.refresh_metadata())
            click.echo(f"Done. Refreshed metadata for {count} items.")
        else:
            llm = _build_llm(config, required=True)
            initializer = GitHubStarsInitializer(
                token,
                db,
                llm,
                max_pages=max_pages,
                per_page=stars_config.per_page,
                classification_batch_size=stars_config.classification_batch_size,
                http_timeout_seconds=stars_config.http_timeout_seconds,
            )
            count = asyncio.run(initializer.run())
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
@click.option("--output", default=None, help="输出文件路径 (默认 reports_dir/github_stars.md)")
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

        out_path = output or os.path.join(config.reports_dir, "github_stars.md")
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

        zotero_config = config.sources.zotero
        if not ZoteroWriteBack.is_available(
            local_api_timeout_seconds=zotero_config.local_api_timeout_seconds
        ):
            click.echo("Error: Zotero local API not available (is Zotero running with HTTP API enabled?)", err=True)
            raise SystemExit(1)

        dry_run = not execute
        if dry_run:
            click.echo("Running in DRY-RUN mode (use --execute to write for real)")
        else:
            click.echo("⚠ EXECUTE mode: will modify Zotero item tags!")

        wb = ZoteroWriteBack(
            db,
            dry_run=dry_run,
            writeback_timeout_seconds=zotero_config.writeback_timeout_seconds,
            local_api_timeout_seconds=zotero_config.local_api_timeout_seconds,
        )
        count = asyncio.run(wb.flush_queue())

        if execute:
            click.echo(f"Done. {count} tags written to Zotero.")
        else:
            click.echo("Dry-run complete. No changes made.")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
