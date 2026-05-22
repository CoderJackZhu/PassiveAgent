# Stage 3: LLM 处理 + 打分 + 排序 + 本地输出

## 前置依赖

Stage 2 完成（能收集真实数据到 DB）

## 目标

接入 DeepSeek API，完成摘要生成、打分、排序，输出 daily_review.md。

## 交付物

- DeepSeekClient (OpenAI 兼容接口封装)
- Summarizer (面试相关度摘要)
- Scorer (6 维度打分)
- Ranker (加权排序 + Top N + Enrich)
- 本地输出 daily_review_{date}.md
- Prompt 模板文件

## 验证标准

```bash
uv run passive-agent daily
# 输出 data/reports/daily_review_2026-05-22.md
# 包含 3 条推荐，每条有摘要、面试价值、分数

cat data/reports/daily_review_2026-05-22.md
# 确认推荐质量：3 条中至少 2 条有价值
```

## 详细任务

### 1. DeepSeekClient

- 基于 openai SDK (AsyncOpenAI)
- base_url = "https://api.deepseek.com"
- 并发信号量限制 (默认 5)
- 支持 JSON mode (response_format)
- 指数退避重试 (2s/4s/8s, 最多 3 次)

### 2. Prompt 模板

创建以下模板文件:
- `prompts/summarize.md.j2` — 摘要生成
- `prompts/score.md.j2` — 打分

模板用 Jinja2 渲染，变量由调用方传入。

### 3. Summarizer

- 输入: list[Item] (stage=new)
- 对每个 item 调用 LLM 生成摘要
- 解析 JSON 输出填充: summary, interview_relevance, estimated_minutes, topics, content_type, recommended_action
- 更新 stage → "summarized"
- 并发处理，单条失败不阻塞其他

### 4. Scorer

- 输入: list[Item] (stage=summarized)
- 获取已有面试卡标题列表 → 传入 prompt 供新颖性判断
- 对每个 item 调用 LLM 打分 (6 维度)
- 计算 weighted_total
- 保存 Score 记录到 scores 表
- 更新 item.priority_score

### 5. Ranker

- 按 priority_score 降序排列
- 取 Top N (默认 3)
- Enrich: 查询 DB 中同 topic 的已有条目作为 "相关旧文章" 提示
- 更新 Top N 的 stage → "recommended"

### 6. 本地输出

生成 `data/reports/daily_review_{date}.md`:

```markdown
# 今日推荐 · 2026-05-22

## ① {title}
- 来源: {source}
- 预计: {estimated_minutes} 分钟
- 面试价值: {interview_relevance}
- 综合评分: {priority_score}/100
- 建议: {recommended_action}

---
(重复 3 条)
```

### 7. Pipeline 完整串联

collect → normalize → dedup → summarize → score → rank → output
