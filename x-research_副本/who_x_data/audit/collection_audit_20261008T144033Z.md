# WHO AI X collection audit

Generated: 2026-10-08T14:40:33+00:00  
Collector: 2.0.0  
twscrape: 0.20.1  
Schema: 2 (`PRAGMA quick_check=ok`)  
Config SHA-256: `2ea60b14d943d3ff6b856adc921fc7f91272afe283301a0e84ec3142b324f132`  
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
| raw_responses | 10 |
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
| p0 | search | partial | 1 |
| p0 | search | pending | 334 |
| p1 | detail | pending | 3 |
| p1 | replies | pending | 3 |
| p1 | search | pending | 114 |
| p1 | thread | pending | 3 |
| p2 | search | pending | 302 |

## Recent runs

| Run | Status | Started UTC | Ended UTC | Jobs | Requests/attempts | Throttle wait seconds |
|---|---|---|---|---:|---:|---:|
| 2809a319288b7bbb606f6c9c | stopped:time_budget | 2026-10-08T14:32:33+00:00 | 2026-10-08T14:40:33+00:00 | 1 | 4 | 22.0 |
| af2db7800a1653a84f177568 | stopped:accounts_unavailable | 2026-10-08T14:13:43+00:00 | 2026-10-08T14:17:02+00:00 | 1 | 6 | 86.0 |
| 4e2b46a82e099ef767b2765d | stopped:accounts_unavailable | 2026-10-08T14:11:24+00:00 | 2026-10-08T14:12:22+00:00 | 1 | 0 | 0.0 |

## Flagged jobs

| Label | Start | End exclusive | Status | Stop reason | Note/error |
|---|---|---|---|---|---|
| F20-01 | 2020-07-10 | 2020-07-17 | partial | hard_time_budget |  |
| health_promoter | 2024-05-07 | 2024-05-14 | error |  | NoAccountError: No account available for queue SearchTimeline |
| health_promoter | 2024-04-30 | 2024-05-07 | empty |  | Empty response: not proof that no matching posts exist |
| health_promoter | 2024-04-23 | 2024-04-30 | empty |  | Empty response: not proof that no matching posts exist |
| health_promoter | 2024-04-16 | 2024-04-23 | empty |  | Empty response: not proof that no matching posts exist |
| health_promoter | 2024-04-02 | 2024-04-09 | empty |  | Empty response: not proof that no matching posts exist |
| formal_name | 2024-05-28 | 2024-06-01 | empty |  | Empty response: not proof that no matching posts exist |
| formal_name | 2024-05-21 | 2024-05-28 | empty |  | Empty response: not proof that no matching posts exist |
| formal_name | 2024-05-14 | 2024-05-21 | empty |  | Empty response: not proof that no matching posts exist |
| formal_name | 2024-05-07 | 2024-05-14 | empty |  | Empty response: not proof that no matching posts exist |
| formal_name | 2024-04-30 | 2024-05-07 | empty |  | Empty response: not proof that no matching posts exist |

## Account pool (credential-free aliases)

| Alias | Active | Endpoint locks | Request counters | Last used |
|---|---|---|---|---|
| acct_051b1465 | True | `{"SearchTimeline":"2026-10-08 14:38:35"}` | `{"UserByScreenName":1,"SearchTimeline":88}` | 2026-10-08 14:37:35 |
| acct_2f9b905d | True | `{}` | `{"SearchTimeline":0}` | 2026-10-08 14:40:33 |
| acct_41bc888e | True | `{"SearchTimeline":"2026-10-08 14:30:53"}` | `{"SearchTimeline":0}` | 2026-10-08 14:15:53 |

## Rate and recovery controls

- Total concurrency defaults to 1 and is capped at 3.
- Each account has one in-flight HTTP request globally; the minimum interval is 10.0 seconds and applies to internal pagination requests.
- Reliable endpoint headers trigger a reserve at 20%; the endpoint waits for reset instead of consuming the reserve.
- Every response body is stored before parsing. Request headers, cookies, tokens, passwords, and account usernames are not stored in the research database or exports.
- Cursors are checkpointed after each yielded page. A non-null cursor at an unexpected end is partial/pagination-stalled, not complete.
- Legacy v1 rows retain their parsed twscrape objects, but no historical HTTP bodies existed to migrate; the raw-response layer begins with v2 requests.

## Known coverage limits

- These are posts still publicly accessible and searchable at collection time, not a complete historical archive.
- Search, reply, thread, `conversation_id:` and `url:` behavior can change and must be validated with known posts. Displayed reply/quote counts do not guarantee retrievability.
- Empty jobs remain `empty_unverified`; local caps, repeated/unresolved cursors, rate limits, authentication failures, and parse failures are distinct outcomes.
- Quoted or reposted objects embedded in a response are relations only until separately fetched as their own detail job.
- Interaction counts and user profiles are collection-time snapshots, not historical values from 2020/2022/2024.
