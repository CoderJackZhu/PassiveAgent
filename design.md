# Passive Agent Workbench — 系统设计文档

## 1. 系统定位

### 1.1 核心问题

信息过载导致注意力浪费。具体表现为：

- 微信公众号收藏数百篇，几乎不回看
- Zotero 存储上千文章并分类，极少深入阅读
- Obsidian 中技术文档和面试资料持续增长，注意力一次只能消化一部分
- GitHub 已 star 1000+ 仓库，大部分未整理未使用
- 信息散布在多个系统中，缺乏统一决策入口

瓶颈不是缺资料，而是不知道先看什么、看完后缺乏沉淀。

### 1.2 系统目标

建立一个「注意力调度系统」：

```
已有信息池 → 少量高价值候选 → 碎片时间 review → 确认后深入处理 → 沉淀为可复用知识
```

系统默认只生成候选，不执行任何不可逆动作。所有写入操作必须经过人工确认。

### 1.3 当前优化目标

面试准备（Agent 算法岗），因此打分、推荐、沉淀模板均偏向：

- Agent 工程与架构
- Tool Calling
- RAG 与评测
- Workflow / Orchestration
- Coding Agent
- LLM Infra
- 模型评测方法论

目标可通过配置文件切换（面试结束后可调整为其他方向）。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────┐
│                    Mac mini (常驻)                    │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌───────────┐    ┌────────────┐    ┌───────────┐  │
│  │ Collectors │───→│ Processors │───→│ Queue     │  │
│  └───────────┘    └────────────┘    └─────┬─────┘  │
│                                           │        │
│                                     每晚 21:00     │
│                                           │        │
│                                           ▼        │
│                                    ┌────────────┐  │
│                                    │ 飞书推送    │  │
│                                    └──────┬─────┘  │
│                                           │        │
│                                     用户点击按钮   │
│                                           │        │
│                                           ▼        │
│  ┌───────────┐    ┌────────────┐    ┌───────────┐  │
│  │ Archive   │←───│ Executor   │←───│ Feishu    │  │
│  │           │    │            │    │ Callback  │  │
│  └───────────┘    └────────────┘    └───────────┘  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 2.1 进程模型

Mac mini 上运行两个组件：

| 组件 | 形式 | 职责 |
|------|------|------|
| 定时任务 | launchd plist，每晚 21:00 触发 | 收集 → 处理 → 打分 → 生成队列 → 推送飞书 |
| 回调服务 | 常驻轻量 HTTP 服务（飞书 SDK 长连接模式） | 接收飞书按钮回调 → 执行 action → 回复确认 |

飞书 SDK 长连接模式由客户端主动连接飞书服务器，不需要公网 IP，不需要内网穿透。

### 2.2 不引入 Hermes

飞书卡片按钮交互已覆盖所有操作需求，不引入额外的自然语言命令层。原因：

- 按钮无歧义，比自然语言解析更可靠
- 减少一层依赖和故障点
- 碎片时间操作场景下，点按钮比打字更快

---

## 3. 数据源与收集策略

### 3.1 数据源清单

| 数据源 | 收集方式 | 频率 | 说明 |
|--------|---------|------|------|
| Zotero 最近新增 | 读取本地 zotero.sqlite | 每日 | 只取最近 7 天新增条目 |
| Obsidian inbox | 读取 inbox.md 文件 | 每日 | 用户手动写入的待处理条目 |
| GitHub stars | 一次性导入 + 被动索引 | 初始化一次 | 不跟踪 release，仅在相关时浮现 |

### 3.2 不纳入第一版的数据源

- 微信公众号自动抓取（稳定性差、合规风险）
- GitHub release 跟踪（多数仓库未实际使用，跟进无意义）
- arXiv / RSS / 金融资讯（等核心闭环验证后再扩展）

### 3.3 Obsidian inbox 格式约定

```markdown
## 2026-05-22
- [LangGraph 新文档](https://xxx) #agent
- 微信看到一篇 Tool Calling 失败分析，搜"xxx"能找到
- Zotero 里那篇 RAGAS 可以看看

## 2026-05-21
- [某篇论文标题](https://arxiv.org/abs/xxx)
- 同事推荐的一个 workflow 框架，叫 xxx
```

规则：
- 有链接就存链接
- 没链接写关键词或描述（LLM 解析意图）
- 可选加 `#tag`
- 不要求严格格式，系统用 LLM 理解每条内容的含义
- 用户可通过任何方式写入此文件（手动编辑、iOS 快捷指令、其他自动化）

### 3.4 Zotero 收集细节

**读取**：以 immutable 模式打开本地 `~/Zotero/zotero.sqlite`（`?immutable=1`，跳过锁机制，Zotero 运行时可正常读取），提取字段：

- itemID / key
- title
- creators（作者）
- date（发表/收录时间）
- dateAdded（加入 Zotero 时间）
- collections（所属分类）
- tags（已有标签）
- attachments（PDF / snapshot 路径）
- abstractNote（摘要，如有）

筛选条件：`dateAdded` 在最近 7 天内。

**写回（打 tag）**：通过 Zotero 本地 HTTP API（`http://localhost:23119/api`）执行，不直接写入 SQLite。Zotero 运行时该 API 可用；若 Zotero 未运行（API 不可用），将写入操作入队，下次 API 可用时批量执行。

### 3.5 GitHub Stars 处理策略

**初始化阶段（一次性）：**

1. 通过 `gh api` 拉取全部 stars 列表
2. 先用 GitHub repo 自身的 topics + description 做规则分类；无法自动分类的调用 LLM
3. 分批处理（每批 20 个 repo 合并为一次 LLM 调用），控制成本和耗时
4. 存入 SQLite

**日常使用（被动索引）：**

- 不主动推送任何 star 仓库更新
- 当每日推荐中出现某个 topic 时，附带提示"你 star 过这些相关仓库：xxx"
- 仅在内容相关时浮现，不制造额外噪音

### 3.6 Zotero 存量文章处理策略

不做全量扫描。采用「被动激活」机制：

- 当新内容进入处理流程时，系统检查 Zotero 中是否有同 topic 的旧文章
- 如果有相关旧文章，在推荐时附带提示："Zotero 中还有一篇相关的 xxx，要一起看吗？"
- 旧文章不占用每日 3 条推荐名额，仅作为附带信息

可选的一次性操作：用户花 30 分钟对 Zotero collections 标注优先级（高 / 中 / 低 / 过时），系统优先从高优 collection 中激活旧文章。

---

## 4. 处理流程

每日 21:00 触发，顺序执行：

```
1. Collect    从各数据源收集新条目
       ↓
2. Normalize  统一为标准 item 结构
       ↓
3. Dedup      与 SQLite 已有条目去重（标题 + URL 匹配；无 URL 条目用标题模糊匹配）
       ↓
4. Summarize  LLM 生成面试相关度摘要（不是通用摘要）
       ↓
5. Score      多维度打分
       ↓
6. Rank       取 Top 3 生成今日队列
       ↓
7. Enrich     检查是否有相关的 Zotero 旧文章 / GitHub stars
       ↓
8. Push       推送飞书卡片
```

### 4.1 统一 Item 结构

每条内容统一为以下结构存储于 SQLite：

```json
{
  "id": "item_20260522_001",
  "source": "zotero | obsidian_inbox | github_star",
  "title": "文章/仓库标题",
  "url": "原始链接（如有）",
  "local_path": "本地文件路径（如有）",
  "zotero_key": "Zotero item key（如适用）",
  "collected_at": "2026-05-22T21:00:00",
  "content_type": "paper | article | note | repo | doc",
  "topics": ["Agent", "RAG", "Tool Calling"],
  "stage": "new | summarized | recommended | actioned | archived | ignored",
  "summary": "面试相关度摘要（由 LLM 生成）",
  "interview_relevance": "这篇内容能帮你回答什么面试问题",
  "estimated_minutes": 20,
  "priority_score": 82,
  "recommended_action": "read | make_card | make_note | ignore",
  "ignored_count": 0,
  "raw_text": "收集时的原始文本（用于 inbox 行匹配）",
  "created_at": "2026-05-22T21:00:00",
  "actioned_at": null
}
```

### 4.2 摘要生成策略

不做通用摘要。LLM 的 prompt 核心问题是：

> "这篇内容能帮我回答哪个 Agent 算法岗面试问题？如果不能，说明原因。"

输出结构：
- 一句话定位（这是什么）
- 面试相关度（能帮你回答什么问题）
- 建议动作（深读 / 生成卡片 / 仅存档 / 跳过）
- 预计阅读时间

### 4.3 打分维度

6 个维度，每个 0-100 分，加权求和：

| 维度 | 权重 | 说明 |
|------|------|------|
| 当前目标相关性 | 30% | 是否和 Agent 岗面试直接相关 |
| 新颖性 | 20% | 是否是已有笔记中没有覆盖的（基于已生成面试卡/笔记的标题列表判断） |
| 可操作性 | 20% | 能否转化为面试回答、demo、代码 |
| 难度适配 | 10% | 是否适合当前可用时间段阅读 |
| 来源质量 | 10% | 官方文档 / 源码 / 论文 > 泛泛博客 |
| 时效性 | 10% | 近期更新 / 新技术优先 |

权重可通过配置文件调整。

### 4.4 负反馈机制

- 每次"忽略"操作记录该条目的 source、topics、content_type
- 同 topic 最近 10 次推荐中被忽略 ≥ 3 次 → 该 topic 权重降低 15%（滑动窗口计数，非严格连续）
- 同 source 最近 15 次推荐中被忽略 ≥ 5 次 → 该 source 权重降低 20%
- 权重降低有下限（不低于原始权重的 30%），防止某类内容被永久屏蔽
- 权重每 30 天自然恢复 5%，允许兴趣变化

---

## 5. 飞书交互设计

### 5.1 每日推送卡片

推送时间：每晚 21:00

卡片样式：一张卡片包含 3 条候选，每条有独立操作按钮。

```
┌─────────────────────────────────────────────┐
│  今日推荐 · 5月22日                           │
├─────────────────────────────────────────────┤
│                                             │
│  ① LangGraph Checkpoint 机制                │
│  来源：Zotero · Agent 分类 · 预计 20 分钟     │
│  面试价值：Agent 状态恢复与断点续跑             │
│  [展开] [面试卡] [周末] [忽略]                │
│                                             │
│  ② RAGAS 评测框架源码分析                     │
│  来源：Obsidian inbox · 预计 30 分钟          │
│  面试价值：RAG 评测方向，可直接出面试答案        │
│  [展开] [面试卡] [周末] [忽略]                │
│                                             │
│  ③ ReAct vs Plan-and-Execute 对比           │
│  来源：Zotero · Agent 分类 · 预计 15 分钟     │
│  面试价值：Agent 架构选型基础问题               │
│  相关：你 star 过 langgraph, autogen          │
│  [展开] [面试卡] [周末] [忽略]                │
│                                             │
├─────────────────────────────────────────────┤
│  Zotero 中可能相关的旧文章：                   │
│  · "Tool-use Benchmark 2024" (Agent 分类)    │
│  [加入明日推荐] [跳过]                        │
│                                             │
└─────────────────────────────────────────────┘
```

### 5.2 按钮操作与系统响应

| 按钮 | 系统行为 | 飞书反馈 |
|------|---------|---------|
| 展开 | 生成 500-800 字详细摘要 | 新消息发送摘要内容 + 原文位置 |
| 面试卡 | 生成面试问答卡，写入 Obsidian | 卡片该条状态更新为"✓ 面试卡已生成"，新消息发送卡片预览 |
| 周末 | 加入周末队列 | 卡片该条状态更新为"→ 已加入周末" |
| 忽略 | 标记忽略，记录负反馈 | 卡片该条状态更新为"× 已忽略" |

### 5.3 "展开"后的内容呈现

点击"展开"后，系统发送一条新的飞书消息：

```
┌─────────────────────────────────────────────┐
│  展开：LangGraph Checkpoint 机制              │
├─────────────────────────────────────────────┤
│                                             │
│  [500-800 字详细摘要]                        │
│  ...                                        │
│                                             │
├─────────────────────────────────────────────┤
│  原文位置：                                   │
│  · Zotero: Agent > LangGraph Checkpoint     │
│  · 本地路径: ~/Zotero/storage/xxx/xxx.pdf    │
│                                             │
│  [生成面试卡] [生成技术笔记] [标记已读] [关闭]  │
│                                             │
└─────────────────────────────────────────────┘
```

用户查看原文的方式：
- 手机上：打开 Zotero iOS app，定位到对应条目
- Mac 上：打开 Zotero 桌面版，系统提供的路径可直接定位

### 5.4 周末队列推送

每周六 10:00 自动推送本周积累的周末队列：

```
┌─────────────────────────────────────────────┐
│  本周末阅读队列 (3 篇)                        │
├─────────────────────────────────────────────┤
│                                             │
│  ① xxx（周二加入）                            │
│  ② xxx（周三加入）                            │
│  ③ xxx（周五加入）                            │
│                                             │
│  [逐条展开] [全部生成笔记] [清空队列]           │
│                                             │
└─────────────────────────────────────────────┘
```

### 5.5 异常推送

当系统出错时，推送一条简短错误通知：

```
⚠ 今日处理失败
原因：DeepSeek API 超时
影响：今日推荐未生成
处理：明日将补推今日内容
```

### 5.6 主动查询

用户可在飞书 bot 对话中发送文本消息进行查询（有限的几种命令）：

| 用户输入 | 系统响应 |
|---------|---------|
| 本周总结 | 本周处理了 X 条，生成了 Y 张面试卡，忽略了 Z 条 |
| 周末队列 | 展示当前周末队列内容 |
| 最近卡片 | 展示最近 5 张生成的面试卡标题和路径 |
| 暂停 / 恢复 | 暂停或恢复每日推送 |

不做复杂的自然语言理解，仅支持固定关键词匹配。

---

## 6. 动作系统

### 6.1 动作清单

第一版 6 个动作：

| 动作 | 触发方式 | 系统行为 | 输出位置 |
|------|---------|---------|---------|
| 展开 | 飞书按钮 | LLM 生成详细摘要 | 飞书消息 |
| 生成面试卡 | 飞书按钮 | LLM 生成面试问答卡 | Obsidian + 飞书预览 |
| 生成技术笔记 | 展开后按钮 | LLM 生成结构化笔记 | Obsidian + 飞书预览 |
| 加入周末 | 飞书按钮 | 更新 stage 为 weekend | SQLite |
| 忽略 | 飞书按钮 | 标记忽略 + 记录负反馈 | SQLite |
| 标记已读 | 展开后按钮 | 标记已处理 + Zotero 打 tag | SQLite + Zotero |

### 6.2 自动状态流转

```
new → summarized → recommended → actioned → archived
                                    ↘ ignored

状态变更规则：
- collect 阶段：new
- process 阶段：summarized
- 进入当日 Top 3：recommended
- 用户执行任何按钮操作：actioned
- 生成面试卡/笔记/标记已读：archived
- 点击忽略：ignored
- 加入周末：stage 保持 recommended，增加 weekend 标记
```

### 6.3 已读状态管理

SQLite 为阅读状态的唯一权威源。状态变更时反向同步到源系统（Zotero 写回通过本地 HTTP API，见 3.4 节）：

| 动作 | SQLite 状态 | 反向同步 |
|------|------------|---------|
| 生成面试卡 | archived | Zotero 加 tag "✓已处理·面试卡" |
| 生成技术笔记 | archived | Zotero 加 tag "✓已处理·笔记" |
| 标记已读 | archived | Zotero 加 tag "✓已读" |
| 忽略 | ignored | Zotero 加 tag "→已筛·跳过" |

对于 Obsidian inbox 来源的条目：处理完成后在 inbox.md 中对应行末追加 `✓`。匹配方式为按收集时记录的原始行文本做内容匹配（非行号），若原始行已被用户编辑或删除则跳过标记，不阻塞流程。

---

## 7. 输出模板

### 7.1 面试卡模板

写入路径：`Obsidian/01-Interview/{topic}/{标题}.md`

```markdown
---
type: interview-card
topic: [Agent, Tool Calling]
source: 原文标题
source_url: 原文链接
created: 2026-05-22
---

# {面试问题}

## 一句话答案

{一句话精炼回答，30 秒内能说清}

## 展开回答

1. {要点一}
2. {要点二}
3. {要点三}
4. {要点四（如有）}

## 追问预判

- Q: {可能的追问 1}
  A: {回答}
- Q: {可能的追问 2}
  A: {回答}

## 关键细节

{技术细节、数据、源码要点，面试中可以展示深度的内容}

## 原文要点

{从原文中提取的核心论据和例证}
```

### 7.2 技术笔记模板

写入路径：`Obsidian/03-Tech-Notes/{topic}/{标题}.md`

```markdown
---
type: tech-note
topic: [RAG, Evaluation]
source: 原文标题
source_url: 原文链接
created: 2026-05-22
---

# {标题}

## 核心观点

{3-5 个 bullet point}

## 技术细节

{关键实现、架构、算法描述}

## 与已有知识的关联

{和你已有笔记中哪些内容相关}

## 可能的应用场景

{在什么场景下用得上}
```

### 7.3 展开摘要格式（飞书消息内展示）

```
标题：{文章标题}
来源：{source}
预计阅读：{estimated_minutes} 分钟

---

{500-800 字详细摘要，侧重技术核心和面试价值}

---

面试关联：{能帮你回答的面试问题}
建议动作：{深读原文 / 直接生成卡片 / 仅了解即可}
原文位置：{Zotero 路径 / 本地路径 / URL}
```

---

## 8. 存储设计

### 8.1 SQLite 表结构概要

```
items          主表，存储所有收集到的条目及其状态
scores         每条的各维度评分记录
feedback       负反馈记录（用于降权计算）
topic_weights  各 topic 的当前权重（受负反馈影响）
source_weights 各 source 的当前权重
weekend_queue  周末队列
daily_log      每日推送记录
```

### 8.2 文件存储

```
data/
├── workbench.db          SQLite 数据库
├── raw/                  收集到的原始内容缓存
└── reports/              每日/每周报告快照
```

### 8.3 Obsidian Vault 目录约定

```
Obsidian Vault/
├── 00-Inbox/
│   └── inbox.md              用户手动写入的待处理条目
├── 01-Interview/
│   ├── Agent/
│   ├── RAG/
│   ├── Tool-Calling/
│   ├── LLM-Infra/
│   ├── Coding-Agent/
│   └── Workflow/
├── 02-Reading-Queue/
│   └── weekend.md            当前周末队列
├── 03-Tech-Notes/
│   ├── Agent/
│   ├── RAG/
│   └── .../
└── 99-Archive/               低优先级归档
```

---

## 9. 配置管理

### 9.1 goals.yaml — 当前目标定义

```yaml
current_focus: "Agent 算法岗面试准备"
priority_topics:
  - Agent 架构与工程
  - Tool Calling 与 Function Calling
  - RAG 与评测
  - Workflow / Orchestration
  - Coding Agent
  - LLM Infra（推理优化、部署）
  - 模型评测方法论

low_priority_topics:
  - 前端开发
  - 移动开发
  - 泛泛的 AI 趋势文章

output_preference: "interview_card"  # 默认推荐动作偏向生成面试卡
```

### 9.2 sources.yaml — 数据源配置

```yaml
zotero:
  enabled: true
  db_path: "~/Zotero/zotero.sqlite"
  lookback_days: 7
  high_priority_collections: ["Agent", "RAG", "LLM"]
  
obsidian:
  enabled: true
  inbox_path: "~/ObsidianVault/00-Inbox/inbox.md"
  vault_path: "~/ObsidianVault"

github_stars:
  enabled: true
  mode: "passive_index"  # 不主动推送，仅被动关联
```

### 9.3 scoring.yaml — 打分权重配置

```yaml
weights:
  goal_relevance: 0.30
  novelty: 0.20
  actionability: 0.20
  difficulty_fit: 0.10
  source_quality: 0.10
  timeliness: 0.10

daily_limit: 3
weekend_limit: 5

negative_feedback:
  topic_threshold: 3      # 同 topic 连续忽略次数触发降权
  topic_penalty: 0.15     # 降权幅度
  source_threshold: 5
  source_penalty: 0.20
  min_weight: 0.30        # 权重下限
  recovery_days: 30       # 自然恢复周期
  recovery_rate: 0.05     # 每周期恢复幅度
```

---

## 10. 阅读体验设计

### 10.1 阅读入口统一原则

不做统一阅读器。统一的是「决策入口」（飞书），不统一的是「阅读环境」。

```
决策："看什么" → 飞书 bot（所有操作在这里完成）
阅读："怎么看" → 各自最适合的工具
  - 短内容（摘要、卡片预览）→ 飞书消息内直接阅读
  - 中等内容（技术笔记、面试卡）→ Obsidian（Mac）或 iCloud 同步后手机阅读
  - 长内容（论文、完整文章）→ Zotero（Mac / iOS）
```

### 10.2 阅读路径指引

系统在推送和展开时，始终提供原文的访问路径：

- Zotero 来源：提供 collection 名称 + 文章标题（用户在 Zotero 中搜索定位）
- Obsidian 来源：提供文件路径（在 Obsidian 中直接打开）
- 网页来源：提供 URL

### 10.3 阅读完成确认

不设强制"已读确认"流程。判定逻辑：

| 用户操作 | 视为 |
|---------|------|
| 生成面试卡 | 已处理（充分利用） |
| 生成技术笔记 | 已处理（充分利用） |
| 标记已读 | 已读（了解但不深入） |
| 展开后 72 小时无操作 | 自动提醒"还要继续看吗？" |
| 忽略 | 不需要读 |
| 加入周末 | 延后处理 |

---

## 11. 运维与容错

### 11.1 Mac mini 配置要求

- 系统设置：永不休眠
- 网络：保持联网（飞书长连接 + DeepSeek API）
- 存储：SQLite + Obsidian Vault + Zotero 数据库均在本地

### 11.2 容错策略

| 故障场景 | 处理方式 |
|---------|---------|
| DeepSeek API 不可用 | 跳过当天推送，次日补推（合并为最多 5 条） |
| 飞书连接断开 | 自动重连，重连失败记录日志，恢复后补推 |
| Zotero 数据库锁定 | 等待 30 秒重试，3 次失败后跳过 Zotero 源 |
| Obsidian inbox.md 为空 | 正常，仅从其他源收集 |
| 推送后用户无操作 | 不重复推送，次日推新内容 |

### 11.3 日志

- 每日处理日志写入 `data/reports/daily_log_{date}.json`
- 记录：收集条数、处理条数、推送条数、用户操作、错误信息
- 每周自动清理 30 天前的日志

### 11.4 数据备份

- Obsidian Vault：依赖用户已有的同步方案（iCloud / Git）
- SQLite：每周自动备份一份到 `data/backups/`，保留最近 4 份
- 配置文件：纳入项目 Git 管理

---

## 12. 阶段规划

### Phase 1：本地验证（1-2 周）

目标：验证"每日 3 条推荐 + 面试卡生成"是否真正有用。

范围：
- Zotero 最近新增收集
- Obsidian inbox 收集
- DeepSeek V4 Pro 摘要 + 打分
- SQLite 存储
- 输出 daily_review.md（本地文件，手动查看）
- 手动执行 action（CLI 命令生成面试卡）

验证标准：
- 推荐的 3 条中，至少 2 条你愿意进一步看
- 生成的面试卡能直接用于面试复习
- 比你自己翻 Zotero / Obsidian 筛选更省时间

### Phase 2：飞书接入（1 周）

目标：碎片时间可完成 review 和操作。

范围：
- 飞书自建应用 + 机器人
- 卡片消息推送
- 按钮回调执行 action
- 自动写入 Obsidian + Zotero 打 tag

### Phase 3：闭环完善（1-2 周）

目标：系统自适应用户偏好。

范围：
- 负反馈降权
- 周末队列 + 周六推送
- 72 小时未操作提醒
- GitHub stars 被动索引
- Zotero 旧文章被动激活
- 主动查询命令

### Phase 4：扩展（稳定后）

视需求逐步加入：
- 更多数据源（RSS、arXiv）
- Embedding 做相似内容检测
- 目标 profile 切换
- 周报生成

---

## 13. 设计原则

| # | 原则 | 含义 |
|---|------|------|
| 1 | 每日只推少量 | 3 条高质量 > 30 条摘要。不制造新的信息焦虑 |
| 2 | 确认后才沉淀 | 只有用户明确操作后才写入 Obsidian，防止沉淀地变垃圾场 |
| 3 | 服务当前目标 | 所有打分偏向面试准备，目标变更时改配置 |
| 4 | 负反馈必须学习 | 每次忽略都更新权重，系统越用越准 |
| 5 | 被动激活存量 | 不主动扫描 1000+ 旧文章，只在相关时唤醒 |
| 6 | 统一决策不统一阅读 | 飞书做决策入口，阅读在各自工具 |
| 7 | 容错优于完美 | API 挂了就跳过，不阻塞整个流程 |
| 8 | 最小依赖 | 不引入 Hermes、向量库、消息队列等额外组件 |

---

## 14. 边界与不做的事

明确不做：
- 不做统一阅读器
- 不做微信自动化抓取
- 不做 GitHub release 跟踪
- 不做全量文章自动总结
- 不做复杂的自然语言交互
- 不做向量数据库（第一版）
- 不做知识图谱
- 不做自动替用户决策的不可逆操作
- 不做 Web UI / Dashboard（第一版）
