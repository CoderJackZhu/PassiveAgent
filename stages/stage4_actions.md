# Stage 4: Action 系统 (面试卡 / 技术笔记 / 忽略)

## 前置依赖

Stage 3 完成（daily 命令能生成推荐列表）

## 目标

通过 CLI 对推荐条目执行 action，生成面试卡/技术笔记到 Obsidian。

## 交付物

- Action 基类与分发器
- InterviewCardAction (生成面试卡 → Obsidian)
- TechNoteAction (生成技术笔记 → Obsidian)
- IgnoreAction (标记忽略 + 负反馈记录)
- MarkReadAction (标记已读)
- ObsidianWriter (写入 vault)
- ZoteroLocalAPI (写回 tag，带队列)
- 负反馈引擎 (滑动窗口)
- CLI action 子命令

## 验证标准

```bash
# 生成面试卡
uv run passive-agent action item_20260522_001 --type card
# → Obsidian/01-Interview/Agent/xxx.md 文件存在
# → DB 中该 item stage = "archived"

# 忽略
uv run passive-agent action item_20260522_002 --type ignore
# → DB 中该 item stage = "ignored", ignored_count += 1
# → feedback 表有记录

# 查看状态
uv run passive-agent status
# → 显示今日推荐状态、待处理数、已生成卡片数
```

## 详细任务

### 1. Action 协议与分发

```python
class Action(Protocol):
    async def execute(self, item_id: str) -> ActionResult: ...

class ActionDispatcher:
    actions = {"card": InterviewCardAction, "note": TechNoteAction, ...}
    async def dispatch(self, action_type: str, item_id: str) -> ActionResult: ...
```

### 2. InterviewCardAction

- 从 DB 获取 item (含 summary, interview_relevance)
- 渲染 prompts/interview_card.md.j2
- 调用 DeepSeek 生成面试卡内容
- 调用 ObsidianWriter.write_interview_card() 写入文件
- 更新 item stage → "archived"
- 尝试 ZoteroLocalAPI.add_tag() (异步，失败不阻塞)
- 返回 ActionResult (成功消息 + 文件路径)

### 3. TechNoteAction

- 类似 InterviewCardAction，使用 tech_note.md.j2 模板
- 写入 Obsidian/03-Tech-Notes/{topic}/

### 4. IgnoreAction

- 更新 item stage → "ignored"
- item.ignored_count += 1
- 写入 feedback 表
- 调用 FeedbackEngine.update_on_ignore()

### 5. MarkReadAction

- 更新 item stage → "archived"
- ZoteroLocalAPI.add_tag("✓已读")
- ObsidianWriter.mark_inbox_done() (如果来源是 inbox)

### 6. ObsidianWriter

- write_interview_card(item, content) → Path
- write_tech_note(item, content) → Path
- mark_inbox_done(raw_text) → bool
- 文件名安全处理，目录自动创建

### 7. ZoteroLocalAPI

- is_available() — 检查 localhost:23119
- add_tag(item_key, tag) — 通过 HTTP API 写入
- 不可用时入队 zotero_write_queue 表
- flush_queue() — 每次 daily 运行时尝试执行队列

### 8. FeedbackEngine

- update_on_ignore(item) — 滑动窗口更新权重
- recover_weights() — 由 daily pipeline 调用，检查 30 天恢复

### 9. Prompt 模板

- `prompts/interview_card.md.j2`
- `prompts/tech_note.md.j2`
- `prompts/expand.md.j2` (展开摘要，为后续飞书阶段准备)

### 10. CLI 扩展

```
passive-agent action <item_id> --type [card|note|ignore|read]
passive-agent status          # 今日推荐状态概览
passive-agent list             # 列出最近推荐条目及其状态
```
