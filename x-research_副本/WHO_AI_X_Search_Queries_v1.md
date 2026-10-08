# WHO AI 健康传播研究：X 完整检索语句清单 v1

编制日期：2026-10-08。性质：拟执行检索方案，未登录 X 试跑；不声称检索完整，也不声称每条语句已经验证有效。

## 使用方式

本清单包含 92 条固定关键词/账号检索式、6 条已知链接检索式和 8 条动态模板。MF 的 5 条语句分别用于两个窗口，因此固定关键词/账号部分展开后为 97 个“检索式×窗口”，加 6 个链接任务后为 103 个全窗口任务；继续按 7 天或 1 天切片后，实际任务数会增加。不要把 103 理解为 HTTP 请求次数。

- P0：核心检索，优先执行；P1：第二轮补充；P2：专项或多语言补漏，先检查增量再扩大。
- 所有固定关键词语句可送入 twscrape 的 search/search_raw；含 url:、conversation_id: 的语句须先验证当前后端支持情况。
- 默认 Latest，不加 lang:en、不设置最低互动数、不排除回复。Top 只作为独立的查漏任务记录。
- 表中的完整语句覆盖整个观察窗口；正式运行由调度器替换日期，生成互不重叠的 7 天子窗口，密集时缩至 1 天。
- 本项目本地时间纳入规则为 start <= published_at_utc < end；不要只依赖服务器对日期操作符的解释，必须二次检查时间。
- 普通空格代表共同出现；OR 用大写；使用半角双引号。复杂括号检索若不稳定，拆成多个简单查询并求并集。
- WHO 是英文常用词，大小写和引号不能让它自动变成机构实体；SARAH、Florence 也是常见人名。宽查询预期包含噪声，原始层保留，后续筛选。
- “S.A.R.A.H.” 与 “S.A.R.A.H” 可能被搜索系统归一化为相同词项；只在试采确认无新增且行为一致后停用冗余变体，保留停用记录。
- 每个 ID 是 query_id，不是编码标签。固定版本为 who_ai_x_queries_v1。任务哈希包含完整查询、日期、查询版本、模式、种子及平台。
- 不按三个账号重复执行同一清单；使用共享队列领取不同任务，按各自接口额度运行。

## 观察窗口

| 窗口 | 起点（UTC，含） | 终点（UTC，不含） | 用途 |
|---|---|---|---|
| W20 | 2020-07-10 | 2020-08-09 | Florence 发布后30天 |
| W22 | 2022-10-04 | 2022-11-03 | Florence 2.0 发布后30天 |
| W24 | 2024-04-02 | 2024-06-01 | SARAH 发布及后续讨论 |

W24 可在本地分为 04-02–04-18、04-18–05-02、05-02–06-01 三个半开区间，不必为时期标签重复抓取。同等30天比较时，对 SARAH 取 04-02–05-02 子集。发布前背景可另加7天，但不自动纳入主窗口。年份或窗口本身不能证明帖子讨论的是哪代产品。

## 固定检索式

### F20 — Florence 2020：基础检索（P0）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| F20-01 | W20 | `Florence "World Health Organization" since:2020-07-10 until:2020-08-09` |
| F20-02 | W20 | `Florence WHO since:2020-07-10 until:2020-08-09` |
| F20-03 | W20 | `Florence @WHO since:2020-07-10 until:2020-08-09` |
| F20-04 | W20 | `Florence "digital health worker" since:2020-07-10 until:2020-08-09` |
| F20-05 | W20 | `Florence "virtual health worker" since:2020-07-10 until:2020-08-09` |
| F20-06 | W20 | `Florence "AI health worker" since:2020-07-10 until:2020-08-09` |
| F20-07 | W20 | `Florence chatbot since:2020-07-10 until:2020-08-09` |
| F20-08 | W20 | `Florence "Soul Machines" since:2020-07-10 until:2020-08-09` |
| F20-09 | W20 | `Florence tobacco since:2020-07-10 until:2020-08-09` |
| F20-10 | W20 | `Florence smoking since:2020-07-10 until:2020-08-09` |
| F20-11 | W20 | `"WHO" "digital health worker" since:2020-07-10 until:2020-08-09` |
| F20-12 | W20 | `"World Health Organization" "virtual health worker" since:2020-07-10 until:2020-08-09` |

### F22 — Florence 2.0：基础检索（P0）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| F22-01 | W22 | `"Florence 2.0" since:2022-10-04 until:2022-11-03` |
| F22-02 | W22 | `"Florence version 2.0" since:2022-10-04 until:2022-11-03` |
| F22-03 | W22 | `Florence "World Health Organization" since:2022-10-04 until:2022-11-03` |
| F22-04 | W22 | `Florence WHO since:2022-10-04 until:2022-11-03` |
| F22-05 | W22 | `Florence @WHO since:2022-10-04 until:2022-11-03` |
| F22-06 | W22 | `Florence "digital health worker" since:2022-10-04 until:2022-11-03` |
| F22-07 | W22 | `Florence chatbot since:2022-10-04 until:2022-11-03` |
| F22-08 | W22 | `Florence "Soul Machines" since:2022-10-04 until:2022-11-03` |
| F22-09 | W22 | `Florence WISH since:2022-10-04 until:2022-11-03` |
| F22-10 | W22 | `Florence Qatar since:2022-10-04 until:2022-11-03` |
| F22-11 | W22 | `Florence "mental health" since:2022-10-04 until:2022-11-03` |
| F22-12 | W22 | `"WHO" "AI health worker" since:2022-10-04 until:2022-11-03` |

### S24 — SARAH：基础检索（P0）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| S24-01 | W24 | `"S.A.R.A.H." since:2024-04-02 until:2024-06-01` |
| S24-02 | W24 | `"S.A.R.A.H" since:2024-04-02 until:2024-06-01` |
| S24-03 | W24 | `SARAH "World Health Organization" since:2024-04-02 until:2024-06-01` |
| S24-04 | W24 | `SARAH WHO since:2024-04-02 until:2024-06-01` |
| S24-05 | W24 | `SARAH @WHO since:2024-04-02 until:2024-06-01` |
| S24-06 | W24 | `SARAH chatbot since:2024-04-02 until:2024-06-01` |
| S24-07 | W24 | `SARAH "health assistant" since:2024-04-02 until:2024-06-01` |
| S24-08 | W24 | `SARAH "health promoter" since:2024-04-02 until:2024-06-01` |
| S24-09 | W24 | `SARAH "digital health" since:2024-04-02 until:2024-06-01` |
| S24-10 | W24 | `SARAH "Soul Machines" since:2024-04-02 until:2024-06-01` |
| S24-11 | W24 | `"Smart AI Resource Assistant for Health" since:2024-04-02 until:2024-06-01` |
| S24-12 | W24 | `"WHO" chatbot since:2024-04-02 until:2024-06-01` |
| S24-13 | W24 | `"World Health Organization" chatbot since:2024-04-02 until:2024-06-01` |
| S24-14 | W24 | `"WHO" "digital health promoter" since:2024-04-02 until:2024-06-01` |
| S24-15 | W24 | `"World Health Organization" "generative AI" since:2024-04-02 until:2024-06-01` |
| S24-16 | W24 | `Florence SARAH since:2024-04-02 until:2024-06-01` |

### O20 — WHO 主账号：Florence 2020（P0）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| O20-01 | W20 | `from:WHO Florence since:2020-07-10 until:2020-08-09` |
| O20-02 | W20 | `from:WHO "digital health worker" since:2020-07-10 until:2020-08-09` |
| O20-03 | W20 | `from:WHO "virtual health worker" since:2020-07-10 until:2020-08-09` |
| O20-04 | W20 | `from:WHO "quitting tobacco" since:2020-07-10 until:2020-08-09` |

### O22 — WHO 主账号：Florence 2.0（P0）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| O22-01 | W22 | `from:WHO Florence since:2022-10-04 until:2022-11-03` |
| O22-02 | W22 | `from:WHO "digital health worker" since:2022-10-04 until:2022-11-03` |
| O22-03 | W22 | `from:WHO "AI health worker" since:2022-10-04 until:2022-11-03` |

### O24 — WHO 主账号：SARAH（P0）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| O24-01 | W24 | `from:WHO SARAH since:2024-04-02 until:2024-06-01` |
| O24-02 | W24 | `from:WHO "S.A.R.A.H." since:2024-04-02 until:2024-06-01` |
| O24-03 | W24 | `from:WHO "digital health promoter" since:2024-04-02 until:2024-06-01` |
| O24-04 | W24 | `from:WHO chatbot since:2024-04-02 until:2024-06-01` |

### E24 — 不使用产品名的功能表达补漏（P1）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| E24-01 | W24 | `"WHO" "AI assistant" since:2024-04-02 until:2024-06-01` |
| E24-02 | W24 | `"WHO" "health bot" since:2024-04-02 until:2024-06-01` |
| E24-03 | W24 | `"World Health Organization" "artificial intelligence" since:2024-04-02 until:2024-06-01` |
| E24-04 | W24 | `"Soul Machines" "World Health Organization" since:2024-04-02 until:2024-06-01` |
| E24-05 | W24 | `"Soul Machines" WHO since:2024-04-02 until:2024-06-01` |
| E24-06 | W24 | `"digital health promoter" since:2024-04-02 until:2024-06-01` |
| E24-07 | W24 | `"WHO" "AI nurse" since:2024-04-02 until:2024-06-01` |
| E24-08 | W24 | `"WHO" "AI doctor" since:2024-04-02 until:2024-06-01` |

### G24 — 风险、责任及治理专项补漏（不是编码类别）（P2）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| G24-01 | W24 | `(SARAH OR "S.A.R.A.H.") (wrong OR inaccurate OR incorrect) since:2024-04-02 until:2024-06-01` |
| G24-02 | W24 | `(SARAH OR "S.A.R.A.H.") (hallucination OR hallucinations OR hallucinate OR hallucinating) since:2024-04-02 until:2024-06-01` |
| G24-03 | W24 | `(SARAH OR "S.A.R.A.H.") (fabricated OR invented OR fake) since:2024-04-02 until:2024-06-01` |
| G24-04 | W24 | `(SARAH OR "S.A.R.A.H.") (hospital OR hospitals OR clinic OR clinics) since:2024-04-02 until:2024-06-01` |
| G24-05 | W24 | `(SARAH OR "S.A.R.A.H.") (lecanemab OR Alzheimer) since:2024-04-02 until:2024-06-01` |
| G24-06 | W24 | `(SARAH OR "S.A.R.A.H.") (misinformation OR disinformation) since:2024-04-02 until:2024-06-01` |
| G24-07 | W24 | `(SARAH OR "S.A.R.A.H.") (responsibility OR responsible OR accountability OR accountable) since:2024-04-02 until:2024-06-01` |
| G24-08 | W24 | `(SARAH OR "S.A.R.A.H.") (trust OR credibility OR reputation) since:2024-04-02 until:2024-06-01` |
| G24-09 | W24 | `(SARAH OR "S.A.R.A.H.") (oversight OR audit OR testing OR evaluation) since:2024-04-02 until:2024-06-01` |
| G24-10 | W24 | `(SARAH OR "S.A.R.A.H.") (privacy OR bias OR transparency) since:2024-04-02 until:2024-06-01` |
| G24-11 | W24 | `(SARAH OR "S.A.R.A.H.") (withdraw OR disable OR "shut down") since:2024-04-02 until:2024-06-01` |
| G24-12 | W24 | `(SARAH OR "S.A.R.A.H.") (access OR equity OR inequality) since:2024-04-02 until:2024-06-01` |
| G24-13 | W24 | `"WHO" chatbot (wrong OR fake OR fabricated) since:2024-04-02 until:2024-06-01` |
| G24-14 | W24 | `"World Health Organization" chatbot (risk OR safety OR trust) since:2024-04-02 until:2024-06-01` |
| G24-15 | W24 | `"WHO" chatbot (responsibility OR accountability OR oversight) since:2024-04-02 until:2024-06-01` |
| G24-16 | W24 | `"WHO" chatbot ("medical advice" OR "medical answers") since:2024-04-02 until:2024-06-01` |

### M24 — 多语言补充起始集（候选词，须试跑）（P2）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| M24-01 | W24 | `SARAH (世卫 OR 世衞 OR 世衛 OR 世卫组织 OR 世衛組織 OR 世界卫生组织 OR 世界衛生組織) since:2024-04-02 until:2024-06-01` |
| M24-02 | W24 | `(莎拉 OR 萨拉 OR 莎菈) (世卫 OR 世衛 OR WHO) since:2024-04-02 until:2024-06-01` |
| M24-03 | W24 | `(世卫 OR 世衛 OR 世界卫生组织 OR 世界衛生組織) (聊天机器人 OR 聊天機器人 OR 人工智能) since:2024-04-02 until:2024-06-01` |
| M24-04 | W24 | `SARAH OMS since:2024-04-02 until:2024-06-01` |
| M24-05 | W24 | `SARAH "Organisation mondiale de la santé" since:2024-04-02 until:2024-06-01` |
| M24-06 | W24 | `SARAH "Organización Mundial de la Salud" since:2024-04-02 until:2024-06-01` |
| M24-07 | W24 | `SARAH "Organização Mundial da Saúde" since:2024-04-02 until:2024-06-01` |
| M24-08 | W24 | `SARAH (chatbot OR "intelligence artificielle" OR "inteligencia artificial" OR "inteligência artificial") since:2024-04-02 until:2024-06-01` |
| M24-09 | W24 | `(SARAH OR Сара) (ВОЗ OR "Всемирная организация здравоохранения") since:2024-04-02 until:2024-06-01` |
| M24-10 | W24 | `(SARAH OR سارة OR سارا) "منظمة الصحة العالمية" since:2024-04-02 until:2024-06-01` |
| M24-11 | W24 | `(SARAH OR サラ) (WHO OR 世界保健機関) since:2024-04-02 until:2024-06-01` |
| M24-12 | W24 | `(SARAH OR 사라) (WHO OR 세계보건기구) since:2024-04-02 until:2024-06-01` |

### MF — Florence 多语言补充起始集（两个窗口分别执行）（P2）

| ID | 窗口 | 完整检索语句 |
|---|---|---|
| MF-01 | W20 | `Florence OMS since:2020-07-10 until:2020-08-09` |
| MF-01 | W22 | `Florence OMS since:2022-10-04 until:2022-11-03` |
| MF-02 | W20 | `Florence (世卫 OR 世衛 OR 世界卫生组织 OR 世界衛生組織) since:2020-07-10 until:2020-08-09` |
| MF-02 | W22 | `Florence (世卫 OR 世衛 OR 世界卫生组织 OR 世界衛生組織) since:2022-10-04 until:2022-11-03` |
| MF-03 | W20 | `(弗洛伦斯 OR 弗洛倫斯) (WHO OR 世卫 OR 世衛) since:2020-07-10 until:2020-08-09` |
| MF-03 | W22 | `(弗洛伦斯 OR 弗洛倫斯) (WHO OR 世卫 OR 世衛) since:2022-10-04 until:2022-11-03` |
| MF-04 | W20 | `(Florence OR Флоренс) ВОЗ since:2020-07-10 until:2020-08-09` |
| MF-04 | W22 | `(Florence OR Флоренс) ВОЗ since:2022-10-04 until:2022-11-03` |
| MF-05 | W20 | `(Florence OR فلورنس) "منظمة الصحة العالمية" since:2020-07-10 until:2020-08-09` |
| MF-05 | W22 | `(Florence OR فلورنس) "منظمة الصحة العالمية" since:2022-10-04 until:2022-11-03` |

## 已知链接检索式（P1，先验证 URL 运算符）

不加 SARAH 或 Florence 词：目的是找只分享链接、正文不提产品名的帖子。url: 的解析、路径匹配和短链展开会受后端影响，这不是已验证的完整引用检索。匹配后核对返回对象的 expanded URL。失败时使用下面的精确 URL/路径文本备选，并把失败状态记录下来。

| ID | 窗口 | 完整候选语句 |
|---|---|---|
| L20-01 | W20 | `url:www.who.int/news/item/10-07-2020-who-and-partners-to-help-more-than-1-billion-people-quit-tobacco-to-reduce-risk-of-covid-19 since:2020-07-10 until:2020-08-09` |
| L20-02 | W20 | `url:www.who.int/news-room/feature-stories/detail/ai-for-quitting-tobacco-initiative since:2020-07-10 until:2020-08-09` |
| L22-01 | W22 | `url:www.who.int/news/item/04-10-2022-who-and-partners-launch-world-s-most-extensive-freely-accessible-ai-health-worker since:2022-10-04 until:2022-11-03` |
| L24-01 | W24 | `url:www.who.int/news/item/02-04-2024-who-unveils-a-digital-health-promoter-harnessing-generative-ai-for-public-health since:2024-04-02 until:2024-06-01` |
| L24-02 | W24 | `url:www.bloomberg.com/news/articles/2024-04-18/who-s-new-ai-health-chatbot-sarah-gets-many-medical-questions-wrong since:2024-04-02 until:2024-06-01` |
| L24-03 | W24 | `url:fortune.com/2024/04/18/who-new-ai-powered-chatbot-sarah-basic-health-information-giving-wrong-medical-answers since:2024-04-02 until:2024-06-01` |

对每个链接按顺序试验三种形式，不默认全部重复运行：

1. `url:{DOMAIN_AND_PATH} since:{START} until:{END}`
2. `"{FULL_URL}" since:{START} until:{END}`
3. `"{DISTINCTIVE_PATH_SLUG}" since:{START} until:{END}`

这些是替代形式；文本检索可能匹配正文而非链接，不等于引用关系。采集响应里出现的 t.co/buff.ly 等短链应保留原值及 expanded URL；只有已有具体短链时再试搜该短链，不猜短链。WHO 公告的语言路径变体只有核实存在后再加入。

## 动态检索模板（P1，必须填入真实值）

| ID | 候选检索式 | 说明 |
|---|---|---|
| D01 | `from:{VERIFIED_HANDLE} Florence since:{START} until:{END}` | 核实身份后的区域WHO、合作方、媒体或记者账号；窗口选W20/W22 |
| D02 | `from:{VERIFIED_HANDLE} (SARAH OR "S.A.R.A.H.") since:{START} until:{END}` | W24；复杂OR失效时拆为两条 |
| D03 | `conversation_id:{ROOT_CONVERSATION_ID} since:{START} until:{END}` | 不加任何产品名或立场词；先验证操作符 |
| D04 | `url:twitter.com/{ROOT_AUTHOR}/status/{POST_ID} since:{START} until:{END}` | 候选引用/分享；以返回字段确认关系 |
| D05 | `url:x.com/{ROOT_AUTHOR}/status/{POST_ID} since:{START} until:{END}` | 新域名变体，仅有增量时保留 |
| D06 | `url:{VERIFIED_ARTICLE_DOMAIN_AND_PATH} since:{START} until:{END}` | 新发现的相关报道 |
| D07 | `"{DISTINCTIVE_ARTICLE_TITLE_PHRASE}" since:{START} until:{END}` | 已核实报道中的辨识性短语；避免泛泛“AI health” |
| D08 | `to:{ROOT_AUTHOR} (SARAH OR Florence OR chatbot) since:{START} until:{END}` | 低优先级回复补漏；不能代替讨论串采集 |

ROOT_CONVERSATION_ID 从响应的 conversationId 取得，不能无条件把某个子回复 ID 当成整个对话根 ID。根会话含多个分支，须保存 inReplyToTweetId 等关系辨识种子相关分支。D08会漏掉“this is dangerous”之类不提名称的短回复，因此不能作为回复主入口。

账号发现范围：WHO 主账号、在结果或官方网页中核实的 WHO 区域账号及相关负责人、Soul Machines、相关新闻媒体及记者。不要凭猜测填账号，不把合作方、负责人个人账号或媒体账号直接认定为WHO组织官方传播；本阶段仅保存作者原始资料与核实来源。

当前没有已验证的种子帖清单；所有大括号参数都需要替换，未替换的模板不得入运行队列。

## 非检索任务：必须与语句清单一起使用

纯文本关键词无法获取所有不含关键词的回复。按当前 twscrape 项目文档，可安排以下接口任务；先检查本机安装版本：
- tweet_details(POST_ID)：补齐种子、缺失父帖、引用原帖。
- tweet_replies(POST_ID)：分页获取可返回的回复，与D03互补，不保证整串完整。
- tweet_thread(POST_ID)：补充上下文；不要假定它等同完整回复树。
- 优先使用对应 raw 方法保留原始响应；同一ID不重复调度已完成的补全任务。

返回的 parent、conversation、quoted、retweeted 原生字段用于重建关系。抓父帖时不套主观察窗口，但在采集日志记录 context_fetch 与原始发布时间。观察窗口外的上下文不能自动进入研究统计。

## 执行顺序与去重

1. 第一轮 P0：F20、F22、S24、O20、O22、O24，共51条语句；固定在每个相应窗口执行。
2. 发现种子即建立回复/引用任务，不等所有关键词跑完。轮流分页，避免一个热门串占完预算。
3. 第二轮 P1：E24、L类已知链接、D类核实后的动态模板。
4. 第三轮 P2：G24、M24、MF；分批试跑，查看新增唯一ID和噪声，再决定扩大。
5. 多语言清单是起始候选集合，不是穷尽的语言覆盖。M24-08仅匹配SARAH chatbot的英文部分可能与S24重叠，作用主要是追加其他语种词项；若无增量停用。
6. G24的大量结果应已被基础检索覆盖。它们仅用来发现搜索遗漏/排名截断，不把专项命中当成“责任表达”或其他研究标签。
7. 同一帖子保存一次实体；retrieval_hits保留全部query_id、job_id、run_id、根种子与检索模式，专项语料来源不得丢失。
8. 任务为空记empty_unverified；达到本地上限或重复游标记partial，不写成全量完成。先用已知可访问的历史帖子检查搜索有效性。
9. 无新增不能证明该时期无讨论；低增量只能支持暂停重复检索。无法返回、删除、私密、索引遗漏等都是覆盖限制。

## 需要保留的最小检索元数据

query_id、query_version、query_text、window_start_utc、window_end_exclusive_utc、product(Latest/Top)、seed_post_id、conversation_id、endpoint、run_id、job_id、collected_at_utc、cursor/可恢复检查点、response_status、stop_reason、account_alias（不得存认证凭据）。

这些都是技术溯源字段，不是coding schema。研究立场、情绪、身份、责任归因等暂不写入原始数据库。

## 依据与核实来源

名称、功能描述和日期用于选择检索词；以下资料不代表实际X检索结果。

- Florence首发：[WHO, 2020-07-10](https://www.who.int/news/item/10-07-2020-who-and-partners-to-help-more-than-1-billion-people-quit-tobacco-to-reduce-risk-of-covid-19)
- Florence专题：[WHO, 2020-07-13](https://www.who.int/news-room/feature-stories/detail/ai-for-quitting-tobacco-initiative)
- Florence 2.0：[WHO, 2022-10-04](https://www.who.int/news/item/04-10-2022-who-and-partners-launch-world-s-most-extensive-freely-accessible-ai-health-worker)
- SARAH：[WHO, 2024-04-02](https://www.who.int/news/item/02-04-2024-who-unveils-a-digital-health-promoter-harnessing-generative-ai-for-public-health)
- X基本检索语法：[X Help](https://help.x.com/en/using-x/advanced-postdeck-features)
- 接口与Latest/raw方法：[twscrape项目文档](https://github.com/vladkens/twscrape)

说明：X Help的日期描述不能替代本项目半开时间区间规则；日期边界以返回的UTC时间作本地校验。此清单没有验证当前账号、频率额度或后端结果。

