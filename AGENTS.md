# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11 project using a `src/` layout. Application code lives in `src/passive_agent/`; `main.py` defines the Click CLI and `pipeline.py` coordinates the daily workflow. Core packages are organized by responsibility: `collectors/` ingest Zotero, Obsidian, and GitHub Stars data; `processors/` normalize, deduplicate, score, summarize, and rank items; `actions/` handle user decisions; `integrations/` wrap external services; `storage/` owns SQLite models and database access; `feishu/` contains bot callbacks and cards. Tests live in `tests/`, prompt templates in `prompts/`, documentation in `docs/`, and launchd helpers in `scripts/`. Runtime data such as `data/workbench.db` should remain untracked.

## Build, Test, and Development Commands

- `uv sync --all-extras`: install runtime and development dependencies from `pyproject.toml` and `uv.lock`.
- `uv run pytest tests/ -v`: run the full test suite.
- `uv run passive-agent init-db`: initialize the local SQLite database.
- `uv run passive-agent daily`: run the daily collection, processing, and recommendation pipeline.
- `uv run passive-agent status`: inspect item counts by stage.

Use `pip install -e ".[dev]"` only when working without `uv`.

## Coding Style & Naming Conventions

Follow existing Python style: 4-space indentation, type hints on public interfaces, dataclasses for typed configuration, and small modules grouped by feature. Use `snake_case` for functions, variables, files, and CLI options; use `PascalCase` for classes. New collectors should implement the base collector interface with `is_available()` and `collect()`. New actions should inherit `BaseAction` and implement `execute(item_id)`.

## Testing Guidelines

Tests use `pytest`. Name files `test_*.py` and keep package-specific tests under matching folders such as `tests/test_collectors/` or `tests/test_processors/`. Prefer fixtures like those in `tests/conftest.py` for temporary configs and databases. Add focused tests for new collectors, processors, storage migrations, and action behavior. Run `uv run pytest tests/ -v` before submitting changes.

## Commit & Pull Request Guidelines

Git history uses concise Conventional Commit prefixes, especially `feat:` and `fix:`. Keep commit messages imperative and scoped to one logical change, for example `feat: add github stars refresh command`. Pull requests should include a short summary, test results, configuration or migration notes, and screenshots only when Feishu card output changes. Link related issues when applicable.

## Security & Configuration Tips

Do not commit `config.yaml`, local databases, generated reports, or API keys. Start from `config.yaml.example` and provide secrets through environment variables such as `DEEPSEEK_API_KEY`, `GITHUB_TOKEN`, `ZOTERO_API_KEY`, `FEISHU_APP_ID`, and `FEISHU_APP_SECRET`.
