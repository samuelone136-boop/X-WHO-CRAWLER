# WHO AI X 数据采集系统 v2

本项目为 Florence（2020）、Florence 2.0（2022）和 S.A.R.A.H.（2024）建立可恢复、可审计的 X 原始数据底库。它只使用已经授权的 `accounts.db` 会话访问公开内容；不会重置平台限流、轮换代理、解决验证码或绕过登录/访问控制。

完整的全量目标、执行流程、完成条件、表结构和逐字段数据字典见 [`WHO_AI_X_Full_Collection_System_Spec.md`](WHO_AI_X_Full_Collection_System_Spec.md)。

## 已核实环境

- Python 3.12.2（项目 `.venv`）
- twscrape 0.20.1
- 三个 active 账号，由 twscrape 的共享账号池领取任务；研究库只记录不可逆账号别名，不记录用户名、Cookie、令牌、认证头或密码
- 原 v1 数据保留于 `who_x_data/research.sqlite`，迁移前备份位于 `who_x_data/backups/`

## 采集顺序

1. `p0`：51 条基础/官方检索式，按 7 天切片为 335 个初始任务。
2. 种子详情、回复与 thread 补全；详情返回真实作者 handle 后才建立 URL 引用帖检索，避免猜账号。
3. `p1`：功能表达和 6 条已知链接检索；动态模板只有填入并核实真实值后才能启用。
4. `p2`：风险/治理、多语言与 Florence 多语言补漏。
5. 达到本地阈值时自动把搜索窗口二分至 1 天；单日仍达阈值标为 `saturated`，不声称完整。

查询表直接读取并校验 `WHO_AI_X_Search_Queries_v1.md`：103 个固定“检索式×窗口”行（原清单中的 92 条固定表达、6 条链接及 MF 跨两个窗口展开）和 8 个禁用中的动态模板。核心窗口统一按 UTC 半开区间二次检查。

## 初始化与查看计划

```bash
cd ~/x-research
source .venv/bin/activate
python who_x_collector.py plan --stage all
python who_x_collector.py init --stage all
python who_x_collector.py status
```

`init` 对旧库只做增量加列/建表；首次迁移会先调用 SQLite backup API 创建一致性备份。

## 60–90 分钟试采

先保持总并发为 1：

```bash
python who_x_collector.py run \
  --stage p0 --mode search \
  --concurrency 1 --max-minutes 75
```

试采完成后查看请求数、等待时间、每个任务返回量、唯一帖子和停止原因：

```bash
python who_x_collector.py status
python who_x_collector.py audit
```

确认稳定后才可把 `--concurrency` 提高到 2 或 3；配置和程序都把最大值锁定为 3。无论总并发多少，每个账号全局最多一个在途 API 请求，任意两个分页/API 请求至少间隔 10 秒。限额头可靠时按“账号×接口”预留 20%，等待对应 reset。项目在进程内将 twscrape 的异常 `AsyncHTTPTransport(retries=3)` 替换为已验证可访问 X 的 httpx 默认 transport，并把网络超时提高到 30 秒；重试/退避仍由 QueueClient 和本调度器控制，不修改 `.venv` 包文件。

## 分阶段运行与恢复

整个固定清单可由持久调度器顺序执行；每段最多运行 60 分钟后保存审计，并继续剩余任务。若当前试采还在运行，用 `--wait-pid <现有采集进程 PID>` 接续它。单账号间隔与并发参数保持不变；遇限流按该接口 reset 等待，账号全部失效时等待重新认证。分页卡住只额外复查一次，其他瞬时错误最多复查三次，仍失败则保留覆盖缺口。空结果、单日饱和和解析失败不会被改写为完成。

```bash
python who_x_full_run.py start
python who_x_full_run.py status
python who_x_collector.py status
```

调度器按 P0 搜索 → 上下文 → 种子回复 → P1 搜索 → P2 搜索 → 新发现上下文的顺序执行，阶段结束自动导出。状态与日志位于 `who_x_data/full_run/`，关闭本聊天不会取消已经启动的本地进程；电脑需保持开机和联网。8 个动态模板只在提供并核实实际值后执行，不自动猜测 ID/URL。`finished_with_gaps` 表示已遍历可执行清单且有需核实的覆盖缺口，不代表 X 内容完整。重复启动和并行采集进程会被文件锁拒绝。

```bash
# 基础宽检索
python who_x_collector.py run --stage p0 --mode search

# 种子详情、缺失父帖/引用原帖/会话根帖
python who_x_collector.py run --stage p1 --mode context

# 直接回复与 thread 时间线（解析层保留直接和嵌套回复）
python who_x_collector.py run --stage p1 --mode replies

# 链接与功能表达补漏
python who_x_collector.py run --stage p1 --mode search

# 风险、治理、多语言补漏
python who_x_collector.py run --stage p2 --mode search

# 恢复 partial / rate_limited / auth_error 任务；使用已保存 cursor
python who_x_collector.py resume --stage all --mode all

# 明确重试 empty_unverified
python who_x_collector.py resume --stage all --mode all --retry-empty
```

`Top` 只作独立查漏，任务身份与 `Latest` 分离：

```bash
python who_x_collector.py run --stage p1 --mode search --product Top --max-jobs 10
```

## 数据层

- `raw_responses`：逐个实际 HTTP 响应的原始 body、安全响应头、查询参数、接口、状态、游标与不可逆账号别名。
- `posts`：去重后的原生 Post ID、完整可得正文、UTC 时间、实体、展开链接和媒体元数据。
- `post_relations`：reply、conversation root、quote、repost 关系；嵌套 quoted/retweeted 对象不会冒充已单独抓取的帖子。
- `user_snapshots`、`metric_snapshots`：每次返回时的资料/指标快照；`null` 不改写为 0。
- `runs`、`jobs`、`job_events`、`throttle_events`：配置版本、完整查询、时间窗、种子、游标、状态、等待与错误。
- `retrieval_hits`：同一帖子由哪些 query/job/run/response 发现，Post ID 去重不会丢失命中路径。
- `annotations`：人工编码权威层；导出会先吸收旧 CSV 的 `relevance_label`、`notes`，并保留任意自定义人工列。

旧 v1 的 15 条帖子只有 twscrape 解析对象，没有历史原始 HTTP body；系统明确保留这一缺口，不伪造 raw response。

## 导出

```bash
python who_x_collector.py export
```

输出包括：

- 稳定人工工作表：`who_x_data/coding/master_posts.csv`
- 带时间戳证据包：`who_x_data/exports/<UTC timestamp>/`
- 原始响应 JSONL、解析帖子 JSONL、命中、关系、用户/指标快照、任务与运行 CSV
- `who_x_data/audit/latest_collection_audit.md`

导出采用临时文件后原子替换；不会把现有人工列置空。

## 状态语义

- `complete`：此次接口已无下一游标；不代表平台内容完整。
- `empty_unverified`：本次为空，必须核查已知帖子/操作符，不能解释为零讨论。
- `partial`：时间预算、异常中断或非空游标未解决，可恢复。
- `split_parent` / `saturated`：达到本地阈值后已拆窗 / 单日仍达阈值。
- `rate_limited`：所有账号在该接口等待 reset。
- `auth_error`：没有 active 授权会话；暂停账号，不绕过验证。
- `parse_error`：响应已保存，但当前解析器无法解释。

## 验证

```bash
python -m py_compile who_x_core.py who_x_runtime.py who_x_collector.py
python -m unittest -v
```

测试覆盖查询正文进入任务键、跨查询去重命中、UTC 边界、快照追加、旧库幂等迁移、游标状态字段，以及重复导出保留人工编码。

## 覆盖边界

历史搜索、`url:`、`conversation_id:`、回复与 thread 返回都受当前 X 后端和可见性影响；显示的回复数/引用数不等于可获取数量。2026 年采集到的是仍公开且仍被索引的历史内容，互动指标和用户资料也是 2026 年采集快照，不能还原 2020/2022/2024 当时数值。
