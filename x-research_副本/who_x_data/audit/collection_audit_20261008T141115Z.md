# WHO AI X collection audit

Generated: 2026-10-08T14:11:15+00:00  
Collector: 2.0.0  
twscrape: 0.20.1  
Schema: 2 (`PRAGMA quick_check=ok`)  
Config SHA-256: `e99474c0ebe1f9776e0198cbfcf24e9ac9050ce1823517413575483afb162124`  
Query registry: `WHO_AI_X_Search_Queries_v1.md` / `who_ai_x_queries_v1`

## Registry and scope

- Fixed query×window rows: 103 (P0=51, P1=14, P2=38).
- Dynamic templates documented but disabled until verified values are supplied: 8.
- Core windows are UTC half-open intervals and are checked again against parsed post timestamps.
- Search product defaults to Latest. Top creates separate job identities and is only for gap checks.

## Stored evidence

| Layer | Rows |
|---|---:|
| posts | 15 |
| raw_responses | 0 |
| retrieval_hits | 16 |
| post_relations | 3 |
| user_snapshots | 15 |
| metric_snapshots | 15 |

## Job coverage

| Stage | Kind | Status | Jobs |
|---|---|---|---:|
| legacy | search | complete | 5 |
| legacy | search | empty | 9 |
| legacy | search | error | 1 |
| p0 | search | pending | 335 |
| p1 | detail | pending | 3 |
| p1 | replies | pending | 3 |
| p1 | search | pending | 114 |
| p1 | thread | pending | 3 |
| p2 | search | pending | 302 |

## Account pool (credential-free aliases)

| Alias | Active | Endpoint locks | Request counters | Last used |
|---|---|---|---|---|
| acct_051b1465 | True | `{"SearchTimeline":"2026-10-08 09:57:31"}` | `{"UserByScreenName":1,"SearchTimeline":88}` | 2026-10-08 09:42:58 |
| acct_2f9b905d | True | `{}` | `{}` |  |
| acct_41bc888e | True | `{}` | `{}` |  |

## Rate and recovery controls

- Total concurrency defaults to 1 and is capped at 3.
- Each account has one in-flight HTTP request globally; the minimum interval is 10.0 seconds and applies to internal pagination requests.
- Reliable endpoint headers trigger a reserve at 20%; the endpoint waits for reset instead of consuming the reserve.
- Every response body is stored before parsing. Request headers, cookies, tokens, passwords, and account usernames are not stored in the research database or exports.
- Cursors are checkpointed after each yielded page. A non-null cursor at an unexpected end is partial/pagination-stalled, not complete.

## Known coverage limits

- These are posts still publicly accessible and searchable at collection time, not a complete historical archive.
- Search, reply, thread, `conversation_id:` and `url:` behavior can change and must be validated with known posts. Displayed reply/quote counts do not guarantee retrievability.
- Empty jobs remain `empty_unverified`; local caps, repeated/unresolved cursors, rate limits, authentication failures, and parse failures are distinct outcomes.
- Quoted or reposted objects embedded in a response are relations only until separately fetched as their own detail job.
- Interaction counts and user profiles are collection-time snapshots, not historical values from 2020/2022/2024.
