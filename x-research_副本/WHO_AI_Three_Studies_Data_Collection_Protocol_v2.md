# WHO Florence / Florence 2.0 / S.A.R.A.H. 三研究数据采集方案（v2）

**版本**：2026-10-08；**用途**：CUHK Corporate Communication 团队案例研究；**方案性质**：研究设计与技术改造规范，不等于已执行全部采集。

## 0. 总体目标、方法与结论

核心研究问题：当 AI 以组织身份参与传播时，组织如何管理其自我呈现、利益相关者关系以及因 AI 失败而引发的责任和声誉风险？

- **Study 1 — Longitudinal Framing**：比较 WHO 官方材料和新闻媒体如何描述 Florence（2020）、Florence 2.0（2022）、S.A.R.A.H.（2024）。主分析单位为单篇正式文本/新闻稿/新闻报道；官方 X 帖子和媒体 X 帖子保留为独立平台子语料，不和全文混合估计。
- **Study 2 — Stakeholder Reactions**：比较 2024 年 S.A.R.A.H. 发布、媒体准确性争议和后续三个时期的公开表达。分析单位为去重后的帖子/回复/引用帖；区分关键词检索与种子帖回复两种抽样途径。
- **Study 3 — Responsibility & Governance**：研究 AI 风险/错误表达中，责任指向 WHO、技术供应商还是系统本身，以及提出何种治理诉求。共享 Study 2 的总体候选语料，增补争议专项样本，分别报告宽泛语料比例及重点风险语料主题，不能混合推断总体比例。

不购买 X 付费 API，优先使用已持有的历史样本、WHO 官网、获许可的新闻数据库和 YouTube 官方 API；X 非官方访问只有在适用平台规则和授权允许时才继续使用。平台官方规则禁止未经许可的自动爬取；不建议通过账户轮换、绕过验证码、代理池、重置限流来取得数据。

## 1. 对现有 v1 的代码审计

已检查 `/mnt/data/who-ai-x-collector/who_x_collector.py` 与 `who_x_config.json`；**未接触用户 Mac 上最新实时的 `research.sqlite`**，以下是代码能力评价而非最新样本量统计。

### 保留

- JSON 配置；按 7 天分段；120 条/窗口的预警与自动拆分；Post ID 去重；原始 twscrape 解析 JSON；SQLite job / post / hit；UTC 过滤；`replies` 种子及错误后续跑；CSV 导出。

### v2 必改（P0）

1. `job_key` 现在只包含 `kind|label|start|end`，遗漏查询正文；改为 `SHA256(source|query_text|sort|start|end|seed_id|config_version)`，防止同名查询换词后静默跳过。
2. `export` 当前把 `relevance_label`, `notes` 每次置空；新增 **annotations** 表，记录 `coder_id`, `codebook_version`, `coded_at`, `label`, `note`，导出时 JOIN，禁止从被覆盖的 CSV 作为权威编码库。
3. 将 `posts`, `comments`, `news_documents` 等内容来源统一映射到 `documents` 逻辑层，但必须保留真实类型 `x_post`, `x_reply`, `x_quote`, `youtube_comment`, `who_document`, `news_article` 和平台原始标识；不得把引文中嵌套的 quotedTweet 当独立原帖，除非它被明确单独取得并记录。
4. 新增 `corpus_membership(document_id, study_id, stratum, inclusion_rule, inclusion_status)`：研究归属和采样概率与数据存储相分离。
5. 每次观测记录 `run_id`, `retrieved_at_utc`, `query_version`, `query_exact`, `window_start/end`, `result_rank/order`, `first_seen`, `source_url`；互动量另存 `metric_snapshots`，标明是 2026 年查询时累计指标。
6. 区分 `complete`, `empty_unverified`, `partial`, `rate_limited`, `auth_error`, `pagination_stalled`, `saturated`, `needs_review`，不把无数据认定为真实零记录；不把处理部分错误的任务认定 complete。
7. 续采：保持已写入 post ID；任务运行结果带分页与唯一率日志；页面重复、连续相同 cursor、上界外日期、空窗口要审计；平台限制则正常停止并等待允许再次请求，不轮换账号规避。
8. 有效数据导出时分别生成 `S1_owned_and_news.csv`, `S1_x_posts.csv`, `S2_topic_posts.csv`, `S2_thread_replies.csv`, `S3_risk_subset.csv`, `master_sources.csv`；不要默认所有来源混在 `sarah_posts_for_coding.csv`。

### 可复现质量验证门槛（项目内部判断，不是统计学公认阈值）

- 非空任务：100% 的记录有 ID、时间与来源；所有日期由 Python 依据 UTC 明确二次过滤；所有失败有任务日志。
- 抽查至少 30–50 条候选；编码量充足时抽取 20%–25% 进行双人编码，Krippendorff alpha 目标 ≥0.80；若低于则调整类别定义重新试编码。
- 至少建立 5 条正例 known-post 列表，验证不同查询能否找回；这是“已知条目检索率”，**不是**完整全网 recall。
- 检查每个事件时期的检索任务成功率、唯一帖子数量、超时/空窗口、不匹配的表达和候选数据相关率。

## 2. 统一事件时间轴（UTC；右端不含）

| Event | D0 | Event-window / 计划窗口 | 含义 |
|---|---|---|---|
| Florence | 2020-07-10 | [2020-07-10, 2020-08-09) | WHO 发布初代数字健康工作者，戒烟支持 |
| Florence 2.0 | 2022-10-04 | [2022-10-04, 2022-11-03) | 拓展公共卫生主题和多语言能力 |
| S.A.R.A.H. | 2024-04-02 | [2024-04-02, 2024-06-01) | 生成式 AI 原型，发布与争议 |
| S.A.R.A.H. Accuracy Scrutiny | 2024-04-18 | 比较 P1: 04-02—04-17, P2: 04-18—05-01, P3: 05-02—05-31 | 媒体准确性调查引发讨论 |

可按不同研究单独扩大窗口，但必须记录版本和理由；比较 2020/2022/2024 时优先使用 D0 后等长30天样本，2024 的后30天作为补充分析，避免不同观察长度造成数量假差异。

WHO 官方基础资料：
- https://www.who.int/news/item/10-07-2020-who-and-partners-to-help-more-than-1-billion-people-quit-tobacco-to-reduce-risk-of-covid-19
- https://www.who.int/news/item/04-10-2022-who-and-partners-launch-world-s-most-extensive-freely-accessible-ai-health-worker
- https://www.who.int/news/item/02-04-2024-who-unveils-a-digital-health-promoter-harnessing-generative-ai-for-public-health

## 3. Study 1：WHO vs Media Framing

### 研究问题

S1-RQ1：WHO 在三个版本中如何界定健康传播问题、AI 功能和组织角色？
S1-RQ2：新闻媒体相较 WHO 更强调哪些创新收益、社会风险、责任和管理策略？
S1-RQ3：2024 年4月18日之后，相关媒体文本的风险/责任 framing 有何观察性变化？

### 数据源与分析单位

- **Owned**：WHO 官方新闻稿、官网特写、发言稿、项目页面及官方 X 帖子。按每篇独立发布文本/帖文计数，尽可能符合条件全纳。官方文本数量少时做描述性比较。
- **Earned**：Factiva 中明确讨论 Florence、Florence 2.0 或 S.A.R.A.H. 的独立新闻全文；纪录 URL、媒体名、出版日期、语言、标题、篇幅、原稿/通讯社与可能转载关系。不要把新闻全文与 X 的新闻标题同一总体混合。
- **News on X**：新闻账号在 X 的关联帖子，若数据能合法取得，用作平台内传播话语的次级比较层，而不是新闻全文的替代。

### 检索与抽样

- 三代各以发布日期为 D0，D0—D+29 为主。WHO 官网适当扩展至官方发布前一周，以辨别预热文本，但只在补充分析使用。
- News 先建总体清单。某阶段独立文章 ≤40 时可全部纳入；若更多，可按阶段、媒体类别、地区/语言预先设定分层随机抽取约30–50篇/阶段，避免同一新闻稿的转载充满样本。目标依赖实际供给，不虚构最低数量。
- 非英语如中文/西语应作为语言层标注；若样本不足，主统计限定英语，非英语仅做独立补充，不与英语训练情绪模型无控制混合。

### 内容编码

`project_version, D_from_launch, source_type, media_outlet, outlet_region, headline, issue_context, problem_definition, causal_attribution, moral_evaluation, remedy, generic_frame_conflict, generic_frame_responsibility, generic_frame_human_interest, generic_frame_economic, generic_frame_morality, health_access, innovation, anthropomorphism, AI_role_tool_vs_agent, accuracy_risk, privacy_risk, identity_congruence, coder_id`。

建议 Entman (1993) 的四维框架功能 + Semetko & Valkenburg (2000) 的五种通用新闻框架；本研究扩展变量应经过 pilot 检查，不称作原有验证量表。

### 分析

版本 × WHO/Media 框架比例、每阶段主要 frame 排序、2024 两阶段比较。样本量充足可做卡方/Fisher；对正式文献数量过少或转载聚类严重的情况仅作描述性表述。

## 4. Study 2：Stakeholder Reactions

### 研究问题

S2-RQ1：在发布、争议与后续阶段，不同 stakeholder type 发声涉及哪些 issues？
S2-RQ2：对 S.A.R.A.H. 与 WHO 的 stance 是否有显著差异？
S2-RQ3：不同讨论场域（WHO 官方帖 vs 新闻报道 vs 公开关键词帖子）有什么不同沟通行动和情绪？

### 三个独立抽样层

- `S2-A topic_x`：关键词检索公开帖子。必须标注 query 版本，按日/周分段和时间戳再过滤；不得声称完全代表平台舆论。
- `S2-B who_replies`：以 WHO 发布 S.A.R.A.H. 的同期公开相关帖子为 seed，抓取可见回复；保留 `root_seed_id, parent_id, reply_depth`；推荐至少2–4个 seed，如实际源帖不足则全部。
- `S2-C news_replies`：媒体/记者源帖，按发布后正面/中性/批评内容、发布时期及媒体性质选择。建议初始 6–8 个 seed，不仅3个4月18日负面报道。
- 选配 `S2-D youtube_comments`：仅作为来源独立分析，视频纳入有可重复的频道、关键词和日期规则；YouTube `commentThreads.list` 的 replies 并不保证包含全部回复，需要 `comments.list(parentId=...)` 补齐。讨论场景与X明显不同，不合并成一个“公众支持率”。

### 候选检索策略（每组独立、经网页和已知帖验证，不作为一次复杂 AND）

高准确率：
- `"Smart AI Resource Assistant for Health"`
- `"WHO AI chatbot"`
- `"AI health promoter"`
- `"World Health Organization" "SARAH"`
- `"Soul Machines" "WHO"`

高召回/补充：
- `SARAH WHO`（结果常误匹配常用 who 与人名，需要严格后筛）
- `"digital health promoter"`（检查是否特指 WHO）
- `"WHO" "health assistant"`（只当候选，不保证都相关）

对每种 query 记录 `candidate_count`, `in_date`, `top_level_relevant`, `quote_context_only`, `unique_relevant`, `known_item_found`。全文检索可能匹配 quote、作者等，必须将相关性判断区分 `own_text`、`quoted_text_only`、`thread_context_only`。

### 变量与编码

- Stakeholder：health professional / AI professional / journalist-news / WHO-public institution / nonprofit-NGO / general public-unspecified / other-unclear。必须有本人在同期公开材料的清楚身份依据，否则 unspecified；不能根据 2026 profile 逆推2024身份。
- `stance_sarah`, `stance_who`: positive / negative / mixed / neutral_or_no_stance；两个目标分别编码。
- `emotion`: concern / anger / ridicule / hope / curiosity / none_identifiable / other（多标签可选，先试编码）。
- `issues`: accuracy, safety, access, multilingual, privacy, trust, innovation, bias, governance（可多标签）。
- `communicative_action`: information sharing / question / endorsement / challenge / complaint / call_for_action / other。
- `period`: P1 4/02–4/17，P2 4/18–5/01，P3 5/02–5/31。

预期可编码有效帖子工作目标 200–400，实际无法满足也必须如实报告，不能为了够数量而填充无关材料。同一对话串里的回复可能相关，统计模型要按 `conversation_id` 聚类或以聚合层做稳健性检验。

### 分析

S2：时期 × 议题折线/堆叠图、stakeholder × issue 热力图、AI stance × WHO stance 交叉表、官方场域 vs 媒体场域对比。不得把当前点赞数当作 2024 历史可见值，也不得直接当作态度强弱。

## 5. Study 3：Responsibility Attribution & Governance Demand

### 研究问题

S3-RQ1：在明确涉及错误/风险的相关表述中，责任被指向 WHO / technology vendor / AI system / unspecified 的比例和结构如何？
S3-RQ2：负面 AI 评价是否常伴随对 WHO 的负面评价及明确组织归责？
S3-RQ3：公众提出哪些治理措施，WHO 的传播与 AI 管理可如何响应？

### 两种分母分别报告

- `G1_general`: S2 全部已验证相关帖子，衡量在该获样方式下风险/归责表达的可见占比。
- `G2_issue_enriched`: 对 `wrong medical answers`, `fabricated clinics`, `fake addresses`, `hallucination`, `accountability`, `oversight`, `human review`, `transparency` 等的专项检索，以及争议新闻源帖的回复；提高少见治理观点的覆盖，但不能直接和 G1 相加估计公众总比例。

### 编码

`error_claim` (0/1/unclear), `responsibility_who` (0/1), `responsibility_vendor` (0/1), `responsibility_ai` (0/1), `responsibility_human_users` (0/1), `responsibility_unattributed` (0/1), `stance_sarah`, `stance_who`, `explicit_transfer_to_who` (0/1), `governance_demand` (0/1), `governance_type` (multi-label: verification, transparency, accountability, human oversight, privacy, external audit, equity), `evidence_span`, `coder_id`。

保留批评 AI 但未明确批评 WHO 的文本；不可把共现视作因果声誉外溢，更不可通过帖子断言真实信任水平变化。建议将观察结果表述为 “organizational responsibility attribution and reputational risk signals”。

### 分析

对 AI stance 和 WHO stance 作二维分布；对责任主体 × 治理诉求做矩阵；对 P1/P2/P3 比较并标记样本来源。若某类治理要求极少，只做频数与典型证据，不建过拟合逻辑回归。

## 6. 主数据库（概念模式）与数据字典

| 表 | 主键/必要字段 | 用途 |
|---|---|---|
| `sources` | `source_id, platform, uri, publisher_type` | 所有资源来源统一索引 |
| `documents` | `document_id, source_id, source_native_id, item_type, posted_at_utc, text, language, author_id` | 统一存储正文；保留类型 |
| `document_raw` | `document_id, parser_version, model_json, first_retrieved_at` | 存储原始解析对象；不假称原 HTTP body |
| `retrieval_runs` | `run_id, config_sha, started_at, ended_at, collector_version` | 一次抓取的配置与执行 |
| `jobs` | `job_key, run_id, query_exact, query_hash, start, end, status, raw_count, unique_count, in_range, warning, error` | 断点续采和审计 |
| `retrieval_hits` | `document_id, job_key, observed_at, in_window, rank` | 同一文档多次检索关系 |
| `relations` | `from_id, to_id, relation_type, seed_id` | reply / quoted / repost / linked_to |
| `metric_snapshots` | `document_id, retrieved_at, likes, reposts, replies, quotes, views` | 明确后期累计互动 |
| `corpus_membership` | `document_id, study_id, stratum, include_reason, status` | 三研究独立分母 |
| `annotations` | `document_id, study_id, coder_id, codebook_version, variable, value, evidence_span` | 不受 CSV 再导出影响的编码 |
| `articles` | `document_id, outlet, url, headline, word_count, wire_story_group` | 新闻特有字段 |

**唯一约束**：`(platform, source_native_id)`；无法验证平台原生ID的文稿以已归一化 URL+来源+日期做保守去重，新闻转载另外记录同源关系。

**数据权限**：账户 Cookie 只保存在本机 `accounts.db`，与研究库分离；不提交版本控制。不要公开分发第三方全文、可识别个人资料、完整抓取数据库；按学校研究伦理与许可要求管理原始文本，公开研究可分享经过许可的数据、匿名统计、查询方法和 Post IDs。

## 7. 数据质量与编码工作流

1. 锁定 `research_protocol_v2`, `query_registry_v2`, `codebook_v1`；所有修订新增版本，不覆盖旧版本。
2. 建立已确认真实存在的5–10条 seed posts，按原链接/正文在网页复核存在性与语境；保存核查日期和 ID。
3. 用少量覆盖每个事件时间段的合法/获授权数据做查询回归测试（记录时区、分页、越界、来源）；若无授权改用机构数据和其他可合法访问来源。
4. 对匹配候选在本地按事件窗口、项目、`item_type` 与语言验证；只在逻辑编码层删除无关候选，保留原始材料。
5. 每个分析层各抽30–50条独立编码试样，逐条商议判定边界；修订代码本。
6. 正式编码至少 20–25% 双人复核，按变量汇报一致性，目标 Krippendorff α≥0.80；低于要求时重新训练、简化过细类别并复核。
7. 独立展示采集覆盖报告：候选/唯一/时间内/主帖相关/引文相关/待定/失败/空窗口/已知帖召回/回复完成情况。
8. 只有分析单位和分母稳定后才能作百分比、卡方检验或模型；控制同串/同来源的相关性；少样本优先描述性分析。

## 8. 七天执行表（课程项目的建议进度）

| 日程 | 工作 | 可交付成果 | 停损条件 |
|---|---|---|---|
| Day 1 | 备份旧库；修 v2 任务键、编码持久化、数据分层；锁定 query matrix | v2 schema + versioned config | 不能完整保留 raw/hits/旧任务则不迁移 |
| Day 2 | Study 1 WHO 官网 + News Factiva 搜索与去重；建立媒体总体清单 | S1 owned + news source list | Factiva 没有许可批量下载时改手动/许可方式 |
| Day 3 | S.A.R.A.H. topic corpus，分阶段采集/审核 + WHO官方种子 | S2-A/S2-B + coverage report | 搜索大量错配/空窗口而无法验证则调整到 YouTube |
| Day 4 | 不同场域新闻种子回复，补全合法可见回复；议题风险专项 corpus | S2-C + S3-G2 | 回复可见性太差时不宣称覆盖全部 |
| Day 5 | 30–50 条多来源 pilot，更新编码定义；两名编码员交叉试编码 | codebook v2 + reliability note | 不一致高则先简化变量 |
| Day 6 | 正式编码、统计、可视化，标记小样本限制 | 三研究数据表和图表初稿 | 稀有类别不做不稳健显著性推断 |
| Day 7 | 交叉核查、调整建议与课堂展示，整理复现说明 | Methods appendix、采样流程图、可追踪证据包 | 避免为增加数据量牺牲准确率 |

## 9. 三项研究的最低可交付版本（MVP）

- **S1**：WHO三阶段官方原始声明 + 各阶段可检索独立新闻（足量则定量，欠量则描述性）+ 文本框架矩阵和传播策略解释。
- **S2**：2024三时期分开的、附完整抽样出处的相关文本 + 双目标 stance 与 issue 频率 + 场域差异图。若X公开讨论极稀少则用单独的YouTube评论补充，切忌混合总体估计。
- **S3**：明确引用的错误/责任/治理重点表达 + 责任归因矩阵 + WHO可执行的治理建议；资料少时只做有审计轨迹的探索性定量描述。

**优先级**：先修数据完整性和编码覆盖，再扩关键词；先完整覆盖 2024 S.A.R.A.H.（Study 2/3 共用），再采集 2020/2022 WHO 和新闻材料（Study1）；回复采集的种子尽量多元化，不继续仅放大负面报道讨论串。

## 10. 最重要的可证伪边界

1. 当前可取得的是 2026 年仍公开可检索的历史帖，不是 2024 年完整公共舆论档案。
2. 互动量是抓取时累计量，不代表历史时间点的实时传播效果。
3. 关键词帖子与特定种子回复是不同抽样框架；两者未经过抽样修正不能合并推断总体民意。
4. 人工从帖子判断的是“公开表达的立场/责任归属”，不能推断用户真实心理信任或声誉因果效应。
5. 研究量少时宁可降级为可信的描述性/探索性分析，也不以无关样本填充模型。

## 参考资料

- WHO 2020 Florence: https://www.who.int/news/item/10-07-2020-who-and-partners-to-help-more-than-1-billion-people-quit-tobacco-to-reduce-risk-of-covid-19
- WHO 2022 Florence 2.0: https://www.who.int/news/item/04-10-2022-who-and-partners-launch-world-s-most-extensive-freely-accessible-ai-health-worker
- WHO 2024 S.A.R.A.H.: https://www.who.int/news/item/02-04-2024-who-unveils-a-digital-health-promoter-harnessing-generative-ai-for-public-health
- X terms of service: https://x.com/en/tos
- X automation rules: https://help.x.com/en/rules-and-policies/x-automation
- YouTube comments: https://developers.google.com/youtube/v3/docs/commentThreads/list
- Semetko and Valkenburg (2000): https://doi.org/10.1111/j.1460-2466.2000.tb02843.x
- Entman (1993): https://doi.org/10.1111/j.1460-2466.1993.tb01304.x
- Kim & Grunig STOPS (2011): https://doi.org/10.1111/j.1460-2466.2010.01529.x
