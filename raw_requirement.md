个人需要：我对这个有点感兴趣，需要理清这个工作流需求以及结合现有硬件和软件系统或者额外做一个软件，整体应该是什么样的：“被动时间工作台”

我建议做一个非常实用的系统，不要大而全：

Passive Agent Workbench

核心模块：

1. Collector：收集
2. Filter：筛选
3. Summarizer：摘要
4. Queue：任务队列
5. Review Bot：碎片时间确认
6. Executor：确认后执行
7. Archive：归档沉淀

整体流程：

白天 / 夜间自动运行
        ↓
收集 GitHub / 论文 / 新闻 / 笔记 / 日志
        ↓
去重、分类、摘要、打分
        ↓
生成待 review 队列
        ↓
推送到手机
        ↓
你回复：展开 / 忽略 / 加入周末 / 生成笔记 / 执行
        ↓
系统归档或继续执行

关键是：默认只生成候选，不直接替你做不可逆动作。。。此外额外提供一些参考信息：我微信关注了很多技术公众号，刷到感觉有意义就收藏起来，但是平时几乎不看，然后偶尔有时间把收藏的文章保存到zotero剪存snapshot到本地，但是zotero存了上千文章并分类了，但是也几乎没有怎么看过。现在存了一些技术文档和面试资料为md（为了方便大模型读取整理）使用obsidian或者vscode阅读查看整理，因为在准备面试所以这些技术文档是在看的，不过注意力时间是有限的，一段时间内只能理解阅读明白一部分的内容，内容太多确实很难看完。

回复：

这个方向是有价值的，但要先把目标定准：**不是把微信收藏、Zotero 上千文章、Obsidian 笔记全部“自动学习完”，而是建立一个“注意力调度系统”**。

你的真实问题不是缺资料，而是：

```text
资料太多
收藏太多
真正能读的时间太少
不知道先看什么
看完后缺少沉淀
面试准备需要高优先级知识
技术文章、论文、公众号、Zotero、MD 文档割裂
```

所以这个系统的核心应该是：

```text
把已有信息池 → 变成少量高价值候选 → 你碎片时间 review → 确认后再深入处理 → 沉淀到 Obsidian / 面试资料 / 技术卡片
```

---

# 1. 这个系统应该叫什么

可以叫：

```text
Passive Agent Workbench
```

但从你的场景看，更准确的定位是：

```text
个人知识与学习任务调度系统
Personal Knowledge Triage Agent
```

它不是一个“自动学习系统”，而是一个：

```text
信息初筛器
阅读队列管理器
面试知识沉淀助手
碎片时间 review bot
长期知识归档器
```

---

# 2. 它解决的不是“收藏”，而是“注意力分配”

你现在的信息来源大概是四类：

```text
1. 微信技术公众号收藏
2. Zotero 文章 / snapshot / PDF
3. Obsidian / VS Code 中的 MD 技术文档和面试资料
4. 后续可能加入 GitHub / arXiv / 技术博客 / 金融资料
```

这些资料的问题不是“不存在”，而是没有进入一个统一的决策队列。

所以系统不应该问：

```text
我如何把所有文章都总结？
```

而应该问：

```text
今天我只看 3 条，哪 3 条最值得？
这条内容和我当前面试准备有关吗？
这条内容适合变成面试问答、技术卡片，还是以后再说？
这篇 Zotero 文章和我已有 MD 笔记是否重复？
哪些收藏只是“看起来有用”，其实不值得占用注意力？
```

---

# 3. 总体架构应该是这样

我建议分成 7 层。

```text
                手机 / Review Bot
                       ↑
              Review Queue / 待确认队列
                       ↑
        Summarizer + Scorer + Deduplicator
                       ↑
              Unified Knowledge Store
                       ↑
        Collectors: Zotero / Obsidian / 微信收藏 / GitHub / RSS
                       ↑
                  Mac mini 常驻运行
```

更具体：

```text
Mac mini
├── collectors/
│   ├── zotero_collector.py
│   ├── obsidian_collector.py
│   ├── wechat_inbox_collector.py
│   ├── github_collector.py
│   └── rss_collector.py
│
├── processing/
│   ├── dedup.py
│   ├── classifier.py
│   ├── summarizer.py
│   ├── scorer.py
│   └── queue_builder.py
│
├── storage/
│   ├── sqlite.db
│   ├── raw/
│   ├── snapshots/
│   ├── embeddings/
│   └── reports/
│
├── review_bot/
│   ├── telegram_bot.py / feishu_bot.py / bark_push.py
│   └── actions.py
│
└── archive/
    ├── obsidian_writer.py
    ├── zotero_tag_updater.py
    └── weekly_report.py
```

Hermes 可以放在 `review_bot + memory + executor` 这一层，但不建议让 Hermes 承担所有抓取和处理逻辑。

---

# 4. 现有软件怎么结合

## 4.1 Zotero：作为“重资料库”

Zotero 里上千文章不要直接全量总结。应该把它看成一个 **长期资料库**。

可以做：

```text
读取 Zotero 条目元数据
读取 tags / collection
读取 title / abstract / snapshot / PDF 路径
判断最近新增或最近修改的条目
生成候选阅读队列
```

Zotero 官方提供 Web API，支持读取在线 Zotero library；Zotero 7 也有接近 Web API 的本地 HTTP API，可让同一台机器上的工具读取本地库。([Zotero][1])

如果你希望和 Markdown / LaTeX / JSON 工具链打通，Better BibTeX 是常见方案，它支持把 Zotero 数据更方便地导出到文本工作流中；它也支持自动导出，适合让 Mac mini 周期性读取导出的 `.bib` / `.json`。([Retorque][2])

推荐做法：

```text
Zotero 不直接作为阅读入口
Zotero 作为资料池
系统每天只拿“最近新增 / 最近收藏 / 高相关”的 5-10 条做预筛选
```

---

## 4.2 Obsidian / VS Code：作为“最终沉淀地”

你已经有很多 MD 技术文档和面试资料，这很好。
最终沉淀应该继续放在 Markdown，而不是新造一个复杂知识库。

Obsidian 可以通过 URI 自动打开、定位、创建或修改笔记；Advanced URI 插件就是为了通过 URI 控制 Obsidian 工作流而设计的，适合自动化场景。([Obsidian][3])

所以 Archive 层可以直接写入：

```text
Obsidian Vault/
├── 00-Inbox/
├── 01-Interview/
│   ├── Agent/
│   ├── RAG/
│   ├── Tool-Calling/
│   ├── LLM-Infra/
│   └── Coding-Agent/
├── 02-Reading-Queue/
├── 03-Source-Notes/
├── 04-Cards/
└── 99-Archive/
```

注意：不要把所有摘要都塞进 Obsidian。
应该只写入你确认保留的内容。

---

## 4.3 微信收藏：不要强依赖自动抓取

微信收藏是最麻烦的一环。

你想“通过微信隔一段时间 review 回复一下”，这个交互方式很自然，但个人微信自动化长期不稳定，而且平台规则和 bot 能力有限。Hermes 的 Weixin 文档也明确提到 iLink bot 不能像普通联系人那样被拉进普通微信群，并且普通群消息通常不会送达 gateway。([Hermes Agent][4])

另外，微信近年对批量自动化、AI 生成/聚合内容也更敏感；公开报道提到平台规则禁止无真实人工参与的批量或连续自动发布内容。这里虽然你是个人学习用途，不是运营账号，但依然不建议把个人微信当自动化主通道。([中国新闻网][5])

更稳妥的方案是：

```text
微信只作为“人工发现入口”
真正自动化入口放到 Telegram / 飞书 / 企业微信机器人 / Bark / PushDeer / 邮件
```

微信文章可以这样处理：

```text
方案 A：看到好文章 → 手动分享到 Telegram Bot / 飞书 Bot
方案 B：看到好文章 → 复制链接到 Obsidian inbox.md
方案 C：有空时保存到 Zotero → Mac mini 从 Zotero 读取
方案 D：使用浏览器稍后读工具作为中转
```

不建议第一版就做“自动读取微信收藏”。

---

## 4.4 Hermes：作为 Review Orchestrator，而不是主处理器

Hermes 的合理位置是：

```text
接收你的碎片时间回复
记住你的偏好
调用具体脚本
更新队列状态
触发归档动作
```

不要让 Hermes 负责：

```text
全量抓取 Zotero
全量解析 PDF
全量总结所有文章
大规模向量检索
复杂编码任务
```

这些应该交给稳定脚本和数据库。

Hermes 最适合处理这种交互：

```text
你：2 展开
Hermes：调用 detail_summary.py item_id=xxx

你：加入周末
Hermes：更新 queue.status = weekend

你：生成面试卡
Hermes：调用 create_interview_card.py

你：忽略同类内容
Hermes：记住偏好，降低类似主题权重
```

---

# 5. 数据流应该怎么设计

核心流程如下：

```text
Collector
  ↓
Raw Item
  ↓
Metadata Normalize
  ↓
Dedup
  ↓
Classifier
  ↓
Summary
  ↓
Score
  ↓
Review Queue
  ↓
Human Review
  ↓
Executor
  ↓
Archive
```

每个 item 统一成一个结构：

```json
{
  "id": "item_20260522_001",
  "source": "zotero | obsidian | wechat_inbox | github | rss",
  "title": "文章标题",
  "url": "原始链接",
  "local_path": "本地路径",
  "created_at": "2026-05-22",
  "content_type": "paper | article | note | repo | doc",
  "topic": ["Agent", "RAG", "Tool Calling"],
  "stage": "new | summarized | review_pending | weekend | archived | ignored",
  "summary_short": "一句话摘要",
  "why_relevant": "为什么和当前目标相关",
  "difficulty": 3,
  "estimated_minutes": 15,
  "priority_score": 82,
  "recommended_action": "read | archive | make_card | ignore | weekend"
}
```

---

# 6. Scoring 规则很关键

系统好不好，不取决于能不能总结，而取决于 **排序是否靠谱**。

我建议评分由 6 个维度组成：

```text
1. 当前目标相关性：是否和 Agent 岗面试 / 工作强相关
2. 新颖性：是否是你已有笔记中没有的
3. 可操作性：是否能转化成代码、demo、面试回答或方法论
4. 难度适配：是否适合碎片时间阅读
5. 来源质量：官方文档、源码、论文、优质博客优先
6. 时效性：近期框架更新 / 新技术优先
```

打分示例：

```text
Agent Evaluation 论文，有代码，和面试强相关 → 90 分
公众号泛泛讲大模型趋势 → 35 分
Dify workflow 节点失败机制分析 → 85 分
某篇复杂论文但和当前目标无关 → 45 分
金融短线交易技巧文章 → 20 分
指数基金长期配置入门 → 70 分
```

---

# 7. Review Queue 不要太多

你最大的问题是注意力有限，所以每天推送一定要少。

建议：

```text
每日最多 3 条
每周最多 10 条
每条只给 4 个动作
```

每日推送格式：

```text
今日候选 3 条：

1. LangGraph checkpoint 机制更新
价值：和 Agent 状态恢复、断点续跑有关
建议：加入源码精读
预计时间：20 分钟

2. Tool-use Agent Evaluation 论文
价值：可转化为面试回答和评测 demo
建议：生成技术卡
预计时间：30 分钟

3. 你 Zotero 中一篇 RAGAS 文章
价值：和 RAG 评测有关，但与你已有笔记部分重复
建议：只保留摘要

回复：
1 展开
1 卡片
1 周末
1 忽略
```

这才是碎片时间可执行的。

---

# 8. 你需要的动作集合

不要设计太多动作。第一版 8 个动作足够：

```text
展开
忽略
加入周末
生成面试卡
生成技术笔记
关联已有笔记
标记已读
以后少推类似内容
```

对应行为：

| 动作     | 系统做什么              |
| ------ | ------------------ |
| 展开     | 生成 500-800 字详细摘要   |
| 忽略     | 队列移除，记录负反馈         |
| 加入周末   | 放入 Weekend Queue   |
| 生成面试卡  | 生成 Q&A 型 Markdown  |
| 生成技术笔记 | 生成结构化技术笔记          |
| 关联已有笔记 | 搜索 Obsidian 中相关 MD |
| 标记已读   | 存状态，不再推            |
| 少推类似内容 | 调低相似主题权重           |

---

# 9. 面试准备应该作为最高优先级目标

因为你现在在准备面试，所以系统的默认优化目标应该不是“知识广度”，而是：

```text
提升 Agent 算法岗面试表达能力
```

因此 Archive 模板应该偏面试和工程判断。

比如生成“面试卡”：

```markdown
# Tool Calling 为什么不稳定？

## 一句话回答
Tool Calling 不稳定主要来自工具选择、参数抽取、上下文污染、schema 约束不足和执行反馈处理不当。

## 面试回答框架
1. 问题拆解
2. 常见失败类型
3. 评测指标
4. 优化方案
5. 工程实践案例

## 可展开细节
...

## 关联资料
- xxx
- xxx
```

这比普通摘要有价值得多。

---

# 10. 第一版不要做向量库，先用 SQLite + Markdown

你可能会想上来就做：

```text
ChromaDB
Qdrant
Embedding
GraphRAG
知识图谱
```

但第一版不建议。

因为你的主要瓶颈不是语义搜索，而是 **输入过载和队列管理**。

第一版用：

```text
SQLite：存 metadata、状态、评分、队列
Markdown：存最终笔记
本地文件夹：存 snapshot / raw text
LLM API：做摘要和分类
```

等系统真的用了 2-4 周，再加 embedding。

---

# 11. 推荐 MVP 方案

## MVP 目标

只做三件事：

```text
1. 从 Zotero / Obsidian / 手动 Inbox 收集资料
2. 每天生成 3 条 review 候选
3. 你确认后生成 Obsidian 面试卡 / 技术笔记
```

第一版不要接微信，不要做复杂 UI，不要做全自动抓取。

---

## MVP 输入源

```text
1. Obsidian inbox.md
2. Zotero 最近新增条目
3. 手动保存的 微信文章链接 / 标题
4. 本地 MD 面试资料目录
```

---

## MVP 输出

```text
daily_review.md
weekly_review.md
Obsidian/01-Interview/xxx.md
Obsidian/02-Reading-Queue/xxx.md
```

---

## MVP 推送

优先级：

```text
Telegram Bot > 飞书 Bot > Bark / PushDeer > 邮件 > 微信
```

如果你非常想用微信，建议先只把微信当“人工阅读和收藏入口”，不要把它当 bot 交互主链路。

---

# 12. 未来完整版本

完整版本可以是这样：

```text
Passive Agent Workbench

数据源：
- Zotero
- Obsidian
- 微信文章手动 inbox
- GitHub releases
- arXiv
- Hugging Face
- RSS
- 金融资讯

处理层：
- 去重
- 分类
- 摘要
- 打分
- 相似笔记匹配
- 阅读时间估计

交互层：
- Telegram / 飞书 / Bark
- Hermes 接收命令
- 本地 Web Dashboard

执行层：
- 生成面试卡
- 生成技术笔记
- 加入周末阅读
- 关联已有笔记
- 更新 Zotero tag
- 写入 Obsidian

沉淀层：
- Agent 面试知识库
- 技术卡片库
- 阅读队列
- 金融学习卡
- 周报
```

---

# 13. Mac mini 的角色

你的 Mac mini 应该承担这些：

```text
常驻运行 collector
定时处理 Zotero / Obsidian / inbox
本地保存 SQLite 和 Markdown
调用 LLM API 做摘要
生成每日 review
推送到手机
接收 review 后执行归档
```

它不是为了跑大模型，而是为了成为你的：

```text
个人知识后台处理节点
```

M4 16GB 完全够用，因为主要是：

```text
IO
文本处理
轻量数据库
API 调用
少量本地 embedding
```

---

# 14. Hermes 的角色

Hermes 可以是：

```text
人机交互层
命令路由层
偏好记忆层
执行协调层
```

例如：

```text
你：今天有什么值得看？
Hermes：读取 daily queue，返回 3 条

你：第 2 条生成面试卡
Hermes：调用 card_generator.py

你：以后少推这类公众号文章
Hermes：记录偏好，调整 scorer

你：本周末阅读队列
Hermes：汇总 weekend_queue
```

但是核心数据和逻辑仍然应该放在你自己的系统里，而不是全塞进 Hermes。

---

# 15. 最小目录设计

```text
passive-agent-workbench/
├── config/
│   ├── sources.yaml
│   ├── scoring.yaml
│   └── goals.yaml
│
├── data/
│   ├── workbench.db
│   ├── raw/
│   ├── snapshots/
│   └── reports/
│
├── collectors/
│   ├── zotero.py
│   ├── obsidian.py
│   ├── inbox.py
│   └── rss.py
│
├── processors/
│   ├── normalize.py
│   ├── dedup.py
│   ├── summarize.py
│   ├── score.py
│   └── build_queue.py
│
├── actions/
│   ├── make_interview_card.py
│   ├── make_tech_note.py
│   ├── add_to_weekend.py
│   ├── ignore_item.py
│   └── link_existing_notes.py
│
├── bot/
│   ├── telegram_bot.py
│   └── commands.py
│
├── archive/
│   └── obsidian_writer.py
│
└── main.py
```

---

# 16. 第一个版本的实际工作流

每天晚上 22:00：

```text
1. 读取 Obsidian inbox.md
2. 读取 Zotero 最近 7 天新增条目
3. 读取本地面试资料目录最近修改文件
4. 去重
5. 按 Agent / RAG / Coding Agent / LLM Infra / 金融 分类
6. 生成每条 100 字摘要
7. 打分
8. 选出 Top 3
9. 推送给你
```

你回复：

```text
1 卡片
```

系统执行：

```text
读取第 1 条全文 / 摘要
生成面试问答卡
写入 Obsidian/01-Interview/Agent/
更新 queue 状态为 archived
```

你回复：

```text
2 周末
```

系统执行：

```text
加入 weekend_queue.md
```

你回复：

```text
3 忽略
```

系统执行：

```text
记录 ignored
如果同类连续忽略 3 次，降低该类权重
```

---

# 17. 最重要的产品原则

这个系统要坚持 5 个原则。

## 原则 1：每天只推少量

```text
宁可 3 条高质量，不要 30 条摘要。
```

## 原则 2：默认不自动沉淀

```text
只有你确认“生成笔记 / 生成卡片”后，才写入 Obsidian。
```

否则 Obsidian 会变成新的垃圾场。

## 原则 3：只服务当前目标

当前目标是面试和 Agent 技术成长，所以评分必须偏向：

```text
Agent 工程
Tool Calling
RAG
Workflow
Coding Agent
LLM Infra
模型评测
工程实践
```

## 原则 4：负反馈很重要

你每次点“忽略”，系统都应该学习：

```text
这个来源权重降低
这个主题权重降低
这种标题风格权重降低
```

## 原则 5：沉淀形式必须可复用

不要只生成摘要。
要生成：

```text
面试卡
技术决策卡
源码阅读任务
demo 任务
周末阅读任务
金融知识卡
```

---

# 18. 我建议你第一步做什么

第一步不要写 bot，不要接微信。
先做一个本地 CLI 版本。

```bash
python main.py collect
python main.py build-daily-queue
python main.py review
python main.py action --item 2 --type interview_card
```

先验证：

```text
它推荐的 3 条，你是否真的愿意看？
生成的面试卡是否真的有用？
是否减少了你的筛选成本？
```

如果这一步有价值，再接 Telegram / 飞书 / Hermes。

---

# 19. 最推荐的阶段路线

## 阶段 1：本地 MVP

时间：1 周。

```text
Obsidian inbox + Zotero 最近新增
SQLite 存储
Top 3 daily queue
生成 Markdown review
手动执行动作
```

## 阶段 2：手机 review

时间：第 2 周。

```text
接 Telegram / 飞书 / Bark
支持 展开 / 忽略 / 周末 / 卡片
```

## 阶段 3：Hermes 接入

时间：第 3 周。

```text
Hermes 负责自然语言命令
调用已有 Python action
记录偏好
```

## 阶段 4：扩展数据源

时间：第 4 周以后。

```text
GitHub releases
arXiv
RSS
金融信息
Hugging Face
```

## 阶段 5：加入 embedding

时间：系统稳定后。

```text
相似笔记查找
重复内容识别
相关知识推荐
```

---

# 20. 最终结论

你真正需要的不是“另一个知识库”，而是一个：

```text
注意力分配系统 + 碎片时间 review 系统 + 面试知识沉淀系统
```

它的核心价值是：

```text
让 Mac mini 在你不看资料的时候帮你筛资料
让 Hermes 在你碎片时间帮你处理确认动作
让 Obsidian 成为最终沉淀地
让 Zotero 保持长期资料库角色
让微信收藏不再成为信息黑洞
```

第一版建议极简：

```text
Zotero + Obsidian inbox + SQLite + 每日 Top 3 + 手动/Telegram review + Obsidian 面试卡归档
```

等这个闭环真的跑起来，再考虑微信、Hermes、GitHub、论文、金融资讯。
关键不是自动化越多越好，而是每天稳定帮你做一次：**“今天最值得你花注意力看的东西是什么？”**

[1]: https://www.zotero.org/support/dev/web_api/v3/basics?utm_source=chatgpt.com "dev:web_api:v3:basics [Zotero Documentation]"
[2]: https://retorque.re/zotero-better-bibtex/?utm_source=chatgpt.com "Better BibTeX for Zotero"
[3]: https://publish.obsidian.md/advanced-uri-doc/Home?utm_source=chatgpt.com "Home - Advanced URI Documentation"
[4]: https://hermes-agent.nousresearch.com/docs/ko/user-guide/messaging/weixin?utm_source=chatgpt.com "Weixin (WeChat) | Hermes Agent - nous research"
[5]: https://www.ecns.cn/m/news/society/2026-04-10/detail-ihfcmemi3024920.shtml?utm_source=chatgpt.com "WeChat restricts AI-generated content, stresses role of ..."
