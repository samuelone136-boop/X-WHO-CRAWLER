# WHO AI 健康传播者 X 全量数据采集系统说明

版本：2.0  
文档日期：2026-10-08  
项目目录：`/Users/samuel/x-research`  
主数据库：`/Users/samuel/x-research/who_x_data/research.sqlite`

## 1. 文档目的

本文说明 Florence（2020）、Florence 2.0（2022）和 S.A.R.A.H.（2024）相关 X 数据的最终采集目标、全量任务执行方式、完成条件、SQLite 数据模型和字段定义。

本系统当前只建设可追溯、可恢复的原始证据底库，不生成研究立场、情绪、利益相关者类型或责任归因等自动编码。帖子 ID 去重，但同一帖子通过不同查询、种子或接口被发现的路径全部保留。

“全量完成”在本文中表示：当前版本中具备真实参数的固定查询、种子任务和运行中发现的上下文任务都已被调度，所有未能正常结束的任务均留下状态和缺口记录。它不表示 X 平台历史内容被完整穷尽。

## 2. 最终采集目标

### 2.1 研究对象

| 产品 | UTC 观察窗口（起点含、终点不含） | 主要对象 |
|---|---|---|
| Florence | `[2020-07-10, 2020-08-09)` | WHO 初代数字健康工作者及相关官方、媒体和公众讨论 |
| Florence 2.0 | `[2022-10-04, 2022-11-03)` | 第二代发布、功能描述及相关讨论 |
| S.A.R.A.H. | `[2024-04-02, 2024-06-01)` | 发布、4 月 18 日准确性争议及后续讨论 |

所有搜索结果都用解析后的 `published_at_utc` 再做一次本地 UTC 半开区间检查。窗口外但用于理解回复、引用或会话关系的帖子也可保存，并通过 `retrieval_hits.acquisition_use` 标明获取用途。

### 2.2 要获取的数据

全量任务尽可能获取：

1. 产品名称、功能描述、官方账号、公告链接、报道链接、多语言表达、错误、责任及治理词命中的公开帖子。
2. WHO 及相关媒体/记者的公开源帖。
3. 三个已知媒体种子帖的详情、公开回复和 thread；搜索过程中发现的缺失父帖、引用原帖和会话根帖。
4. 帖子当前可得全文、发布时间、语言、实体、链接、媒体元数据和关系。
5. 接口返回时的作者资料和互动指标快照。
6. 每个实际 HTTP 请求的脱敏请求元数据、原始响应、状态、游标和时间。
7. 查询、任务、运行、限流等待、错误和恢复记录。

当前范围不包含粉丝/关注网络、点赞者名单、转发者名单、所有作者的完整时间线，也不把嵌套的 quoted/retweeted 对象伪装成已经单独抓取的原帖。

### 2.3 查询规模

查询注册表为 `WHO_AI_X_Search_Queries_v1.md`，版本为 `who_ai_x_queries_v1`：

| 层级 | 查询行 | 初始 7 天切片任务 | 用途 |
|---|---:|---:|---|
| P0 | 51 | 335 | 产品基础词、WHO 官方发布及高优先级宽检索 |
| P1 | 14 | 114 | 功能表达、已知链接及第二轮补漏 |
| P2 | 38 | 302 | 风险/治理、多语言及专项查漏 |
| 合计 | 103 | 751 | 默认使用 `Latest` |

此外有 3 个已知种子帖，每个建立 `detail`、`replies` 和 `thread` 任务，共 9 个初始种子任务。采集中发现缺失的关系目标后还会动态建立 `detail` 任务，因此最终任务数可以高于 760。

查询文件另列有 8 个动态模板。它们必须取得并核实真实帖子 ID、会话 ID、账号或 URL 后才能进入配置；当前不会猜测参数或把未实例化模板算作已执行任务。`Top` 只用于独立补漏，也不包含在当前固定清单的默认全量运行中。

原始库没有 200—400 条上限。该数字只可作为后续人工编码工作量参考；采集是否结束由任务覆盖和缺口记录判断。

## 3. 实现方式

### 3.1 组件

| 文件 | 职责 |
|---|---|
| `who_x_full_run.py` | 持久全量调度器；顺序运行阶段、等待已有进程、备份、恢复、导出和记录最终缺口 |
| `who_x_collector.py` | 命令行入口；初始化、运行、恢复、状态、备份、审计和导出 |
| `who_x_runtime.py` | twscrape 请求、逐请求节流、原始响应保存、分页、任务处理和错误分类 |
| `who_x_core.py` | 配置/查询解析、schema、迁移、任务键、帖子记录、快照、导出和审计 |
| `who_x_config.json` | 窗口、阈值、账号库位置、调度参数和种子帖配置 |
| `WHO_AI_X_Search_Queries_v1.md` | 固定查询清单与动态模板定义 |

运行环境为 Python 3.12.2 和 twscrape 0.20.1。账号凭据只存在 twscrape 的 `accounts.db`；研究库只保存账号的不可逆别名。

### 3.2 全量执行顺序

调度器按以下顺序运行：

1. `P0 search`：宽泛基础搜索和 WHO 官方搜索。
2. `all context`：补全当时已发现的父帖、引用原帖、会话根帖及种子详情。
3. `P1 replies`：抓取三个已知种子的回复和 thread。
4. `P1 search`：功能表达和已知链接补漏。
5. `P2 search`：风险、治理和多语言专项检索。
6. `all context`：再次补全前面阶段新发现的缺失关系目标。

每个子运行最长 60 分钟，到时保存游标和任务统计，再由调度器创建下一次子运行。每个阶段结束后自动生成导出快照和审计报告。

### 3.3 查询切片、阈值与分页

- 固定查询先按 7 天切片，服务器查询中显式加入 `since:` 和 `until:`。
- 单个搜索窗口的本地阈值为 120 条。达到阈值后自动二分日期窗口，最小拆到 1 天。
- 单日仍达到阈值时记为 `saturated`，明确留下可能截断的覆盖缺口。
- 回复和 thread 的本地阈值均为 500 条。
- 每页响应先保存到 `raw_responses`，再解析、去重和写入规范化表。
- 每次分页后保存 `cursor`、页数和计数。进程中断时从检查点恢复。
- 非空游标但分页生成器停止时记为 `partial`，全量调度器只额外复查一次，避免无限循环。
- 空响应记为 `empty_unverified`，不解释为真实零讨论。

### 3.4 任务身份与去重

`job_key` 是稳定 SHA-256 身份，输入包含平台、任务类型、标签、完整查询正文、查询版本、采集模式、窗口起止、种子 ID 和搜索产品。查询正文变化会生成新任务，不会因沿用原标签而错误跳过。

`posts.post_id` 是帖子实体主键。相同帖子只保存一行当前规范化记录，但每次发现路径写入 `retrieval_hits`；作者和互动数据按实际响应写入快照表。

### 3.5 请求频率与账号调度

- 当前全量调度使用总并发 1；程序允许的最大总并发为 3。
- 每账号最多一个在途请求。
- 同一账号任意两个实际 HTTP 请求之间至少间隔 10 秒，分页内部请求同样受控。
- 当可靠额度头显示剩余额度达到或低于 20% 时，按“账号 × 接口”等待 reset。
- 当前 HTTP 超时为 30 秒；请求层最多对交易 ID 相关的 404 做 3 次受控重试，每一次都经过节流并留痕。
- 认证不可用时等待账号恢复；连续传输故障达到调度器阈值时暂停并记录原因。
- 日志和研究库不保存 Cookie、令牌、认证头、密码或明文用户名。

### 3.6 恢复、备份与并发保护

- 主库使用 SQLite WAL、`synchronous=FULL` 和 30 秒锁等待。
- 全量调度器接管前使用 SQLite backup API 创建一致性备份，并对备份执行 `PRAGMA quick_check`。
- `collector.lock` 阻止两个采集器同时运行；`supervisor.lock` 阻止重复启动两个全量调度器。
- 上一进程遗留的 `running` 任务会恢复为 `pending`，并记录 `interrupted_previous_run`。
- 时间预算中断可继续；其他瞬时 `partial` 最多复查 3 次；分页卡住只额外复查 1 次。
- `legacy` 阶段仅保留旧数据，不会被 `stage=all` 的全量任务重新领取。

### 3.7 完成状态

| 状态 | 含义 |
|---|---|
| `complete` | 当前接口/任务分页正常结束；不代表平台内容完整 |
| `empty_unverified` | 本次返回空，仍需视为可见性或检索能力缺口 |
| `partial` | 有可恢复进度，或分页/运行异常后未完整结束 |
| `split_parent` | 原窗口达到阈值，已由更小子窗口替代 |
| `saturated` | 最小日期窗口仍达到本地上限 |
| `rate_limited` | 当前可用账号在该接口等待额度重置 |
| `auth_error` | 没有可用的已授权账号会话 |
| `parse_error` | 原始响应已保存，但解析失败 |
| `finished` | 所有可执行任务均以无缺口状态结束 |
| `finished_with_gaps` | 已遍历全量可执行清单，但仍有空结果、饱和、解析错误或其他覆盖缺口 |

## 4. 数据流与表关系

```text
runs ──< jobs ──< raw_responses
 │        │             │
 │        └──< retrieval_hits >── posts
 │                                │
 ├────────────────────────────────┼──< metric_snapshots
 └────────────────────────────────┼──< user_snapshots
                                  ├──< post_relations
                                  ├──< annotations
                                  └──< corpus_membership

jobs/runs ──< job_events
jobs/runs ──< throttle_events
```

SQLite 没有为所有逻辑关系都声明物理外键；分析和清理时仍应按图中的 ID 关系理解。`raw_responses` 是原始 HTTP 证据，`posts.raw_json` 是 twscrape 解析后的单帖对象，两者不能互相替代。

## 5. 表结构与字段

### 5.1 `posts`：去重后的帖子实体

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `post_id` | TEXT, PK | X 原生帖子 ID |
| `published_at_utc` | TEXT, nullable | 帖子发布时间，ISO 8601 UTC |
| `username` | TEXT, nullable | 返回时作者 handle |
| `author_id` | TEXT, nullable | X 原生作者 ID |
| `text` | TEXT, nullable | 当前接口可得的完整正文 |
| `lang` | TEXT, nullable | 平台/接口返回的语言代码 |
| `like_count` | INTEGER, nullable | 最近一次观察到的点赞数；历史快照见 `metric_snapshots` |
| `repost_count` | INTEGER, nullable | 最近一次观察到的转发/重发数 |
| `reply_count` | INTEGER, nullable | 最近一次观察到的回复数 |
| `quote_count` | INTEGER, nullable | 最近一次观察到的引用数 |
| `view_count` | INTEGER, nullable | 最近一次观察到的浏览数 |
| `conversation_id` | TEXT, nullable | 会话根 ID |
| `reply_to_id` | TEXT, nullable | 直接回复的父帖 ID |
| `quoted_id` | TEXT, nullable | 被引用帖 ID |
| `raw_json` | TEXT, NOT NULL | twscrape 解析后的单帖完整 JSON；不是原始 HTTP body |
| `first_retrieved_at` | TEXT, NOT NULL | 首次进入底库的 UTC 时间 |
| `last_retrieved_at` | TEXT, NOT NULL | 最近一次观察到该帖的 UTC 时间 |
| `source_url` | TEXT, nullable | 帖子公开 URL |
| `item_type` | TEXT, NOT NULL | `x_post`、`x_reply`、`x_quote` 或 `x_repost` |
| `entities_json` | TEXT, nullable | hashtags、cashtags、mentioned users 等实体 JSON |
| `links_json` | TEXT, nullable | 解析出的链接数组 JSON |
| `media_json` | TEXT, nullable | 图片、视频、动画等媒体元数据 JSON |
| `acquisition_use` | TEXT, NOT NULL | 该实体首次建立时的获取用途；全部发现路径以 `retrieval_hits` 为准 |

计数缺失时保存 `NULL`，不会默认写成 0。再次发现相同 `post_id` 时更新当前内容和计数，并保留首次获取时间。

### 5.2 `jobs`：最小可恢复任务

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `job_key` | TEXT, PK | 包含完整查询身份的稳定任务哈希 |
| `kind` | TEXT, NOT NULL | `search`、`detail`、`replies` 或 `thread` |
| `label` | TEXT, NOT NULL | 查询 ID、种子标签或自动上下文标签 |
| `query` | TEXT, nullable | 实际执行的完整查询或任务描述，搜索任务含日期操作符 |
| `start_date` | TEXT, nullable | 本地 UTC 校验窗口起点（含） |
| `end_date_exclusive` | TEXT, nullable | 本地 UTC 校验窗口终点（不含） |
| `status` | TEXT, NOT NULL | 当前任务状态 |
| `raw_count` | INTEGER | 接口解析得到的累计条目数，可能包含跨页重复 |
| `unique_count` | INTEGER | 此任务命中的唯一帖子数 |
| `valid_count` | INTEGER | 通过本地 UTC 窗口校验的唯一帖子数 |
| `warning` | TEXT, nullable | 覆盖限制或需人工解释的提示 |
| `error` | TEXT, nullable | 脱敏后的最近错误 |
| `updated_at` | TEXT, NOT NULL | 最近状态/进度更新时间 |
| `platform` | TEXT, NOT NULL | 当前为 `x` |
| `query_version` | TEXT, NOT NULL | 查询注册表版本 |
| `query_hash` | TEXT, nullable | 查询正文 SHA-256 |
| `window_id` | TEXT, nullable | `W20`、`W22` 或 `W24` |
| `product` | TEXT, NOT NULL | 搜索排序产品，通常为 `Latest`；`Top` 单独建任务 |
| `stage` | TEXT, NOT NULL | `p0`、`p1`、`p2` 或旧数据的 `legacy` |
| `mode` | TEXT, nullable | 如 `keyword_search`、`known_link_search`、`dynamic_search`、上下文模式等 |
| `endpoint` | TEXT, nullable | 对应 X/twscrape 接口，如 `SearchTimeline` |
| `seed_post_id` | TEXT, nullable | 种子帖或触发上下文任务的帖子 ID |
| `conversation_id` | TEXT, nullable | 与任务关联的会话 ID |
| `run_id` | TEXT, nullable | 最近领取该任务的运行 ID |
| `parent_job_key` | TEXT, nullable | 拆窗子任务或派生任务的父任务键 |
| `cursor` | TEXT, nullable | 最近分页检查点 |
| `page_count` | INTEGER, NOT NULL | 已处理页数 |
| `request_count` | INTEGER, NOT NULL | 该任务累计实际 HTTP 请求数 |
| `stop_reason` | TEXT, nullable | 结束、暂停或异常的机器可读原因 |
| `created_at` | TEXT, nullable | 任务创建时间 |
| `completed_at` | TEXT, nullable | 达到终态的时间 |
| `config_sha256` | TEXT, nullable | 创建任务时配置文件的 SHA-256 |

### 5.3 `runs`：一次采集器进程运行

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `run_id` | TEXT, PK | 运行唯一 ID |
| `command` | TEXT, NOT NULL | `run` 或 `resume` |
| `mode` | TEXT | 本次运行的任务类型范围 |
| `stage` | TEXT | 本次运行的阶段范围 |
| `product` | TEXT | `Latest` 或 `Top` |
| `config_sha256` | TEXT, NOT NULL | 本次运行配置哈希 |
| `query_version` | TEXT, NOT NULL | 查询版本 |
| `collector_version` | TEXT, NOT NULL | 采集器版本 |
| `twscrape_version` | TEXT, NOT NULL | twscrape 版本 |
| `args_json` | TEXT, NOT NULL | 并发、时限、任务上限等命令参数 JSON |
| `started_at` | TEXT, NOT NULL | 运行开始时间 |
| `ended_at` | TEXT, nullable | 运行结束时间 |
| `status` | TEXT, NOT NULL | `running`、`complete`、`stopped:*` 或 `failed` |
| `jobs_started` | INTEGER, NOT NULL | 领取的任务数 |
| `jobs_finished` | INTEGER, NOT NULL | 本次进程结束处理的任务数 |
| `requests` | INTEGER, NOT NULL | 实际 HTTP 请求次数 |
| `wait_seconds` | REAL, NOT NULL | 请求间隔和额度等待累计秒数 |
| `error` | TEXT, nullable | 运行级脱敏错误 |

### 5.4 `raw_responses`：逐个 HTTP 请求和原始响应

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `response_id` | INTEGER, PK | 本地响应流水号 |
| `run_id` | TEXT, FK nullable | 所属运行 |
| `job_key` | TEXT, FK nullable | 所属任务 |
| `endpoint` | TEXT, NOT NULL | 实际请求接口名 |
| `request_method` | TEXT, NOT NULL | HTTP 方法 |
| `request_json` | TEXT, NOT NULL | 脱敏请求元数据；包含查询、窗口、分页游标和 URL path 等复现字段 |
| `requested_at` | TEXT, NOT NULL | 发出请求时间 |
| `received_at` | TEXT, nullable | 收到响应或错误的时间 |
| `http_status` | INTEGER, nullable | HTTP 状态码；传输异常时可为空 |
| `response_headers_json` | TEXT, nullable | 安全白名单响应头，如 content-type、date 和额度头 |
| `response_body` | TEXT, nullable | 原始 HTTP 响应正文 |
| `response_sha256` | TEXT, nullable | 响应正文 SHA-256，用于完整性检查 |
| `account_alias` | TEXT, nullable | 账号用户名哈希得到的不可逆别名 |
| `cursor_in` | TEXT, nullable | 请求使用的分页游标 |
| `cursor_out` | TEXT, nullable | 从响应提取的下一页游标 |
| `error` | TEXT, nullable | 请求失败时的脱敏错误 |

此表不保存请求头、Cookie、令牌、密码或明文账号名。

### 5.5 `retrieval_hits`：帖子发现路径

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `hit_id` | INTEGER, PK | 命中流水号 |
| `post_id` | TEXT, NOT NULL | 命中的帖子 ID |
| `job_key` | TEXT, NOT NULL | 发现该帖的任务 |
| `run_id` | TEXT, nullable | 发现该帖的运行 |
| `response_id` | INTEGER, nullable | 发现该帖的原始响应 |
| `found_at` | TEXT, NOT NULL | 发现时间 |
| `result_rank` | INTEGER, nullable | 在该任务结果中的本地顺序 |
| `in_window` | INTEGER, nullable | `1` 在核心窗口，`0` 在窗口外，`NULL` 无适用窗口 |
| `acquisition_use` | TEXT, NOT NULL | `topic_search`、`thread_context`、`context_fetch` 或 `legacy_v1` 等获取用途 |

唯一约束为 `(post_id, job_key, response_id)`。分析“某帖子被哪些查询找到”时应使用本表，而不是只看 `posts`。

### 5.6 `post_relations`：帖子关系边

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `relation_id` | INTEGER, PK | 关系流水号 |
| `from_post_id` | TEXT, NOT NULL | 当前已观察帖子 |
| `to_post_id` | TEXT, NOT NULL | 关系指向的目标帖子；目标可能尚未成功获取 |
| `relation_type` | TEXT, NOT NULL | `reply_to`、`conversation_root`、`quotes` 或 `reposts` |
| `seed_post_id` | TEXT, nullable | 若来自种子任务，记录根种子 ID |
| `job_key` | TEXT, nullable | 观察到关系的任务 |
| `first_observed_at` | TEXT, NOT NULL | 首次观察时间 |

同一关系按 `(from_post_id, to_post_id, relation_type, seed_post_id, job_key)` 去重。

### 5.7 `user_snapshots`：作者资料快照

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `snapshot_id` | INTEGER, PK | 快照流水号 |
| `user_id` | TEXT, NOT NULL | X 原生用户 ID |
| `post_id` | TEXT, nullable | 产生本快照的帖子 |
| `run_id` | TEXT, nullable | 所属运行 |
| `job_key` | TEXT, nullable | 所属任务 |
| `response_id` | INTEGER, nullable | 所属原始响应 |
| `retrieved_at` | TEXT, NOT NULL | 快照采集时间 |
| `username` | TEXT, nullable | 当时返回的 handle |
| `display_name` | TEXT, nullable | 显示名 |
| `description` | TEXT, nullable | 个人简介 |
| `location` | TEXT, nullable | 用户填写的位置 |
| `followers_count` | INTEGER, nullable | 当时返回的关注者数 |
| `following_count` | INTEGER, nullable | 当时返回的关注数 |
| `statuses_count` | INTEGER, nullable | 当时返回的发帖总数 |
| `verified` | INTEGER, nullable | 当时返回的认证状态 |
| `protected` | INTEGER, nullable | 当时返回的受保护状态 |
| `profile_json` | TEXT, NOT NULL | 接口可得的完整用户对象 JSON |

唯一约束为 `(user_id, response_id)`。这些值是采集时快照，不能当作 2020/2022/2024 当时的历史数值。

### 5.8 `metric_snapshots`：帖子互动指标快照

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `snapshot_id` | INTEGER, PK | 快照流水号 |
| `post_id` | TEXT, NOT NULL | 帖子 ID |
| `run_id` | TEXT, nullable | 所属运行 |
| `job_key` | TEXT, nullable | 所属任务 |
| `response_id` | INTEGER, nullable | 所属原始响应 |
| `retrieved_at` | TEXT, NOT NULL | 快照采集时间 |
| `like_count` | INTEGER, nullable | 点赞数 |
| `repost_count` | INTEGER, nullable | 转发/重发数 |
| `reply_count` | INTEGER, nullable | 回复数 |
| `quote_count` | INTEGER, nullable | 引用数 |
| `view_count` | INTEGER, nullable | 浏览数 |
| `bookmark_count` | INTEGER, nullable | 收藏数 |

唯一约束为 `(post_id, response_id)`。缺失值为 `NULL`；显示计数不等于接口可实际取得的回复、引用或转发数量。

### 5.9 `annotations`：人工编码权威层

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `annotation_id` | INTEGER, PK | 编码流水号 |
| `post_id` | TEXT, NOT NULL | 被编码帖子 |
| `study_id` | TEXT, NOT NULL | 所属研究，默认 `unassigned` |
| `coder_id` | TEXT, NOT NULL | 编码者标识 |
| `codebook_version` | TEXT, NOT NULL | 编码手册版本 |
| `variable` | TEXT, NOT NULL | 变量名，如 `relevance_label` 或 `notes` |
| `value` | TEXT, nullable | 编码值 |
| `evidence_span` | TEXT, nullable | 支持编码的证据片段 |
| `note` | TEXT, nullable | 编码备注 |
| `coded_at` | TEXT, NOT NULL | 初始编码时间 |
| `updated_at` | TEXT, NOT NULL | 最近修改时间 |

唯一约束为 `(post_id, study_id, coder_id, codebook_version, variable)`。导出前会吸收已有人工 CSV 字段，重复导出不会清空人工编码。

### 5.10 `corpus_membership`：研究语料归属

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `post_id` | TEXT, PK 组成 | 帖子 ID |
| `study_id` | TEXT, PK 组成 | Study 1、2、3 等研究标识 |
| `stratum` | TEXT, PK 组成 | 抽样层，如 topic、WHO replies、news replies |
| `inclusion_rule` | TEXT, nullable | 纳入规则或版本说明 |
| `inclusion_status` | TEXT, NOT NULL | 默认 `candidate`，可记录纳入/排除状态 |
| `recorded_at` | TEXT, NOT NULL | 归属记录时间 |

该表把原始采集与后续研究抽样分开；当前采集阶段可以为空。

### 5.11 `job_events`：任务事件审计

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `event_id` | INTEGER, PK | 事件流水号 |
| `run_id` | TEXT, nullable | 所属运行 |
| `job_key` | TEXT, nullable | 所属任务 |
| `event_at` | TEXT, NOT NULL | 事件时间 |
| `event_type` | TEXT, NOT NULL | 事件类别，如状态变化 |
| `status` | TEXT, nullable | 事件后的任务状态 |
| `detail_json` | TEXT, NOT NULL | 计数、原因等结构化详情 |

### 5.12 `throttle_events`：节流等待审计

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `event_id` | INTEGER, PK | 等待事件流水号 |
| `run_id` | TEXT, nullable | 所属运行 |
| `job_key` | TEXT, nullable | 所属任务 |
| `account_alias` | TEXT, nullable | 不可逆账号别名 |
| `endpoint` | TEXT, nullable | 受控接口 |
| `event_at` | TEXT, NOT NULL | 等待开始记录时间 |
| `reason` | TEXT, NOT NULL | `minimum_interval` 或 `rate_limit_reserve` 等原因 |
| `wait_seconds` | REAL, NOT NULL | 本次计划等待秒数 |

### 5.13 `schema_meta`：schema 元数据

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `key` | TEXT, PK | 元数据键 |
| `value` | TEXT, NOT NULL | 元数据值；当前含 `schema_version=2` |
| `updated_at` | TEXT, NOT NULL | 更新时间 |

### 5.14 `hits`：旧版兼容命中表

| 字段 | 类型/约束 | 含义 |
|---|---|---|
| `post_id` | TEXT, 联合 PK | 帖子 ID |
| `job_key` | TEXT, 联合 PK | 任务 ID |
| `in_window` | INTEGER, NOT NULL | 是否位于任务窗口 |
| `found_at` | TEXT, NOT NULL | 首次命中时间 |

此表用于兼容 v1 数据和旧代码。新的溯源分析应使用信息更完整的 `retrieval_hits`。

## 6. 导出与文件位置

| 路径 | 内容 |
|---|---|
| `who_x_data/research.sqlite` | 持续写入的主数据库，分析时的权威原始底库 |
| `who_x_data/backups/*.sqlite` | SQLite backup API 生成的一致性备份 |
| `who_x_data/exports/<UTC时间>/master_posts.csv` | 某次导出的帖子与人工字段快照 |
| `who_x_data/exports/<UTC时间>/raw_responses.jsonl` | 原始 HTTP 响应证据包 |
| `who_x_data/exports/<UTC时间>/posts_parsed.jsonl` | 解析后的帖子 JSONL |
| `who_x_data/exports/<UTC时间>/*.csv` | 命中、关系、用户/指标快照、任务和运行表 |
| `who_x_data/coding/master_posts.csv` | 稳定路径的人工编码工作表 |
| `who_x_data/audit/*.md` | 采集审计报告 |
| `who_x_data/full_run/status.json` | 全量调度器当前状态 |
| `who_x_data/full_run/collector.log` | 后台调度输出日志 |

导出使用临时文件和原子替换。主库正在采集时可用 Navicat 只读查看；表格视图通常需要手动刷新。避免在采集期间修改 schema 或保持长时间未提交的写事务。

## 7. 常用状态查询

查看全量调度器：

```bash
.venv/bin/python who_x_full_run.py status
```

查看数据库、任务、运行和账号状态：

```bash
.venv/bin/python who_x_collector.py status
```

Navicat 中查看帖子总数和最新写入：

```sql
SELECT COUNT(*) AS total_posts FROM posts;

SELECT post_id, published_at_utc, username, text,
       first_retrieved_at, last_retrieved_at
FROM posts
ORDER BY last_retrieved_at DESC
LIMIT 100;
```

查看任务覆盖和缺口：

```sql
SELECT stage, kind, status, stop_reason, COUNT(*) AS jobs
FROM jobs
WHERE stage IN ('p0', 'p1', 'p2')
GROUP BY stage, kind, status, stop_reason
ORDER BY stage, kind, status, stop_reason;
```

查看某帖的全部发现路径：

```sql
SELECT h.post_id, j.label, j.query, j.stage, j.mode,
       h.run_id, h.response_id, h.in_window, h.acquisition_use
FROM retrieval_hits h
JOIN jobs j ON j.job_key = h.job_key
WHERE h.post_id = :post_id
ORDER BY h.found_at;
```

## 8. 覆盖限制与解释原则

1. 采集发生在 2026 年，只能获得当时仍公开、仍可见且仍被 X 索引的历史内容。
2. 删除、私密、账号停用、搜索索引遗漏、历史排名截断和接口行为变化都会造成缺口。
3. `complete` 只描述本次接口分页结束；`empty_unverified` 不能作为该时期没有讨论的证据。
4. 用户资料和互动指标是采集时快照，不能还原发布当年的数值。
5. `url:`、`conversation_id:`、回复和 thread 的实际可用性取决于当前后端；显示的计数不保证均可取回。
6. 宽检索有意保留噪声；是否与 WHO AI 传播者研究相关，应在后续人工筛选和正式 coding schema 中决定。
7. 最终审计应同时报告已完成任务、空结果、分页卡住、饱和窗口、解析失败、认证/限流等待和未实例化动态模板。

