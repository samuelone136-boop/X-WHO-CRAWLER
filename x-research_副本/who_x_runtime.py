"""Live twscrape execution with request-level throttling and resumable jobs."""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import sqlite3
import time
from contextlib import aclosing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from who_x_core import (
    DATE_SUFFIX,
    config_sha,
    enqueue_missing_context,
    json_dumps,
    make_job,
    record_post,
    resolve_from_config,
    sha256_text,
    twscrape_version,
    update_job,
    utc_now,
    COLLECTOR_VERSION,
)

UTC = timezone.utc
ACTIVE_RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
ACTIVE_JOB_KEY: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_key", default=None)
ACTIVE_ENDPOINT: contextvars.ContextVar[str] = contextvars.ContextVar("endpoint", default="unknown")
ACTIVE_REQUEST_META: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("request_meta", default={})
ACTIVE_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar("deadline", default=None)


class TimeBudgetExceeded(RuntimeError):
    pass


class ParsingFailure(RuntimeError):
    pass


def account_alias(username: str) -> str:
    return "acct_" + hashlib.sha256(username.encode("utf-8")).hexdigest()[:8]


def safe_response_headers(headers: Any) -> dict[str, str]:
    allow = {
        "content-type", "date", "retry-after", "x-rate-limit-limit",
        "x-rate-limit-remaining", "x-rate-limit-reset", "x-response-time",
    }
    return {str(k).lower(): str(v) for k, v in headers.items() if str(k).lower() in allow}


def safe_request_meta(base: dict[str, Any], params: Any) -> dict[str, Any]:
    """Keep reproducibility fields while excluding all headers, cookies, and tokens."""
    output = dict(base)
    if not isinstance(params, dict):
        return output
    variables = params.get("variables")
    if isinstance(variables, str):
        try:
            variables = json.loads(variables)
        except json.JSONDecodeError:
            variables = None
    if isinstance(variables, dict):
        for key in ("rawQuery", "count", "product", "querySource", "cursor", "focalTweetId", "referrer"):
            if key in variables:
                output[key] = variables[key]
        if "cursor" in variables:
            output["cursor"] = variables["cursor"]
    return output


def extract_timeline_cursor(value: Any, preferred: tuple[str, ...] = ("Bottom", "ShowMoreThreads")) -> str | None:
    """Extract a pagination cursor from a raw response without depending on a yielded page."""
    matches: dict[str, str] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            cursor_type = item.get("cursorType")
            cursor_value = item.get("value")
            if isinstance(cursor_type, str) and isinstance(cursor_value, str):
                matches.setdefault(cursor_type, cursor_value)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    for cursor_type in preferred:
        if cursor_type in matches:
            return matches[cursor_type]
    return None


def redact_error(value: BaseException | str) -> str:
    text = str(value)
    text = text.replace("authorization", "[auth]").replace("Authorization", "[auth]")
    return text[:1000]


def install_httpx_timeout_patch(timeout_seconds: float):
    """Use httpx's working default transport plus a longer process-local timeout.

    twscrape 0.20.1 constructs AsyncHTTPTransport(retries=3), which times out on
    X in this environment even when the same request through httpx's default
    transport succeeds. QueueClient already owns bounded retry/backoff policy.
    """
    import httpx
    from twscrape.http import HttpxClient, _resolve_browser

    original = HttpxClient.__init__

    def patched_init(self, *, proxy=None, headers=None, cookies=None, seed=None):
        resolved_headers = dict(headers or {})
        user_agent, _ = _resolve_browser(resolved_headers.get("user-agent"), seed=seed)
        resolved_headers["user-agent"] = user_agent
        self._httpx = httpx
        self._client = httpx.AsyncClient(
            proxy=proxy,
            follow_redirects=True,
            timeout=httpx.Timeout(float(timeout_seconds)),
            headers=resolved_headers,
            cookies=cookies or {},
        )

    HttpxClient.__init__ = patched_init

    def restore() -> None:
        HttpxClient.__init__ = original

    return restore


class RequestThrottle:
    """One request/account, global account spacing, and account×endpoint reserve waits."""

    def __init__(
        self,
        db: sqlite3.Connection,
        min_interval: float,
        reserve_fraction: float,
    ) -> None:
        self.db = db
        self.min_interval = float(min_interval)
        self.reserve_fraction = float(reserve_fraction)
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_account_request: dict[str, float] = {}
        self._endpoint_blocked_until: dict[tuple[str, str], float] = {}

    def _lock(self, username: str) -> asyncio.Lock:
        if username not in self._locks:
            self._locks[username] = asyncio.Lock()
        return self._locks[username]

    async def acquire(self, username: str, endpoint: str) -> asyncio.Lock:
        lock = self._lock(username)
        await lock.acquire()
        now_mono = time.monotonic()
        now_wall = time.time()
        account_wait = max(0.0, self._next_account_request.get(username, 0.0) - now_mono)
        endpoint_wait = max(0.0, self._endpoint_blocked_until.get((username, endpoint), 0.0) - now_wall)
        wait_seconds = max(account_wait, endpoint_wait)
        if wait_seconds:
            reason = "rate_limit_reserve" if endpoint_wait >= account_wait else "minimum_interval"
            run_id = ACTIVE_RUN_ID.get()
            job_key = ACTIVE_JOB_KEY.get()
            self.db.execute(
                """INSERT INTO throttle_events
                   (run_id,job_key,account_alias,endpoint,event_at,reason,wait_seconds)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id, job_key, account_alias(username), endpoint, utc_now(), reason, wait_seconds),
            )
            if run_id:
                self.db.execute("UPDATE runs SET wait_seconds=wait_seconds+? WHERE run_id=?", (wait_seconds, run_id))
            self.db.commit()
            deadline = ACTIVE_DEADLINE.get()
            if deadline is not None and time.monotonic() + wait_seconds >= deadline:
                lock.release()
                raise TimeBudgetExceeded("time budget would expire during throttle wait")
            remaining = wait_seconds
            while remaining > 0:
                pause = min(remaining, 30.0)
                await asyncio.sleep(pause)
                remaining -= pause
        return lock

    def release(self, username: str, endpoint: str, lock: asyncio.Lock, response: Any | None) -> None:
        self._next_account_request[username] = time.monotonic() + self.min_interval
        if response is not None:
            try:
                remaining = int(response.headers.get("x-rate-limit-remaining", -1))
                limit = int(response.headers.get("x-rate-limit-limit", -1))
                reset = int(response.headers.get("x-rate-limit-reset", -1))
            except (TypeError, ValueError):
                remaining = limit = reset = -1
            if limit > 0 and remaining >= 0 and reset > 0 and remaining / limit <= self.reserve_fraction:
                self._endpoint_blocked_until[(username, endpoint)] = float(reset)
        lock.release()


def install_request_hook(db: sqlite3.Connection, throttle: RequestThrottle):
    """Patch the installed 0.20.x request layer for auditable per-HTTP pacing."""
    from twscrape.queue_client import AbortReqError, Ctx, XClIdGenStore
    from twscrape.logger import logger

    original = Ctx.req

    async def audited_req(self, method, url, params=None):
        path = urlparse(url).path or "/"
        endpoint = path.rstrip("/").split("/")[-1] or ACTIVE_ENDPOINT.get()
        tries = 0
        while tries < 3:
            lock = await throttle.acquire(self.acc.username, endpoint)
            requested = utc_now()
            response = None
            response_id = None
            try:
                generator = await XClIdGenStore.get(
                    self.acc.username,
                    proxy=self.proxy,
                    cookies=self.acc.cookies,
                    fresh=tries > 0,
                )
                headers = {"x-client-transaction-id": generator.calc(method, path)}
                response = await self.clt.request(method, url, params=params, headers=headers)
                received = utc_now()
                body = response.text
                run_id = ACTIVE_RUN_ID.get()
                job_key = ACTIVE_JOB_KEY.get()
                meta = safe_request_meta(ACTIVE_REQUEST_META.get(), params)
                meta["url_path"] = path
                cursor_in = meta.get("cursor")
                try:
                    raw_cursor_out = extract_timeline_cursor(response.json())
                except Exception:
                    raw_cursor_out = None
                row = db.execute(
                    """INSERT INTO raw_responses
                       (run_id,job_key,endpoint,request_method,request_json,requested_at,
                        received_at,http_status,response_headers_json,response_body,
                        response_sha256,account_alias,cursor_in,cursor_out)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id, job_key, endpoint, method, json_dumps(meta), requested, received,
                        int(response.status_code), json_dumps(safe_response_headers(response.headers)),
                        body, sha256_text(body), account_alias(self.acc.username), cursor_in,
                        raw_cursor_out,
                    ),
                )
                response_id = int(row.lastrowid)
                setattr(response, "_who_raw_response_id", response_id)
                if run_id:
                    db.execute("UPDATE runs SET requests=requests+1 WHERE run_id=?", (run_id,))
                if job_key:
                    db.execute("UPDATE jobs SET request_count=request_count+1,updated_at=? WHERE job_key=?", (received, job_key))
                db.commit()
            except Exception as exc:
                received = utc_now()
                run_id = ACTIVE_RUN_ID.get()
                job_key = ACTIVE_JOB_KEY.get()
                meta = safe_request_meta(ACTIVE_REQUEST_META.get(), params)
                meta["url_path"] = path
                db.execute(
                    """INSERT INTO raw_responses
                       (run_id,job_key,endpoint,request_method,request_json,requested_at,
                        received_at,account_alias,cursor_in,error)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id, job_key, endpoint, method, json_dumps(meta), requested, received,
                        account_alias(self.acc.username), meta.get("cursor"),
                        f"{type(exc).__name__}: {redact_error(exc)}",
                    ),
                )
                if run_id:
                    db.execute("UPDATE runs SET requests=requests+1 WHERE run_id=?", (run_id,))
                if job_key:
                    db.execute("UPDATE jobs SET request_count=request_count+1,updated_at=? WHERE job_key=?", (received, job_key))
                db.commit()
                raise
            finally:
                throttle.release(self.acc.username, endpoint, lock, response)
            if response.status_code != 404:
                return response
            tries += 1
            logger.debug(f"Retrying request with new x-client-transaction-id: {url}")
        raise AbortReqError("Failed to obtain a valid transaction id after three paced attempts")

    Ctx.req = audited_req

    def restore() -> None:
        Ctx.req = original

    return restore


def start_run(
    db: sqlite3.Connection,
    cfg: dict[str, Any],
    *,
    command: str,
    mode: str,
    stage: str,
    product: str,
    args: dict[str, Any],
) -> str:
    seed = f"{utc_now()}|{time.time_ns()}|{command}|{mode}|{stage}"
    run_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    db.execute(
        """INSERT INTO runs
           (run_id,command,mode,stage,product,config_sha256,query_version,
            collector_version,twscrape_version,args_json,started_at,status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id, command, mode, stage, product, config_sha(cfg), cfg["query_version"],
            COLLECTOR_VERSION, twscrape_version(), json_dumps(args), utc_now(), "running",
        ),
    )
    db.commit()
    return run_id


def finish_run(db: sqlite3.Connection, run_id: str, status: str, error: str | None = None) -> None:
    db.execute(
        "UPDATE runs SET status=?,ended_at=?,error=? WHERE run_id=?",
        (status, utc_now(), error, run_id),
    )
    db.commit()


def _allowed_kinds(mode: str) -> tuple[str, ...]:
    if mode == "search":
        return ("search",)
    if mode == "replies":
        return ("replies", "thread")
    if mode == "context":
        return ("detail",)
    return ("search", "replies", "thread", "detail")


def prepare_jobs_for_run(
    db: sqlite3.Connection,
    *,
    command: str,
    stage: str,
    mode: str,
    retry_empty: bool,
) -> None:
    kinds = _allowed_kinds(mode)
    placeholders = ",".join("?" for _ in kinds)
    stage_clause = " AND stage IN ('p0','p1','p2')" if stage == "all" else " AND stage=?"
    params: list[Any] = list(kinds)
    if stage != "all":
        params.append(stage)
    db.execute(
        f"""UPDATE jobs SET status='pending',stop_reason='interrupted_previous_run',updated_at=?
            WHERE status='running' AND kind IN ({placeholders}){stage_clause}""",
        [utc_now(), *params],
    )
    if command == "resume":
        db.execute(
            f"""UPDATE jobs SET status='pending',updated_at=?
                WHERE status IN ('partial','rate_limited','auth_error')
                AND kind IN ({placeholders}){stage_clause}""",
            [utc_now(), *params],
        )
    if retry_empty:
        db.execute(
            f"""UPDATE jobs SET status='pending',updated_at=?
                WHERE status IN ('empty','empty_unverified')
                AND kind IN ({placeholders}){stage_clause}""",
            [utc_now(), *params],
        )
    db.commit()


def claim_next_job(
    db: sqlite3.Connection,
    *,
    run_id: str,
    stage: str,
    mode: str,
) -> sqlite3.Row | None:
    kinds = _allowed_kinds(mode)
    placeholders = ",".join("?" for _ in kinds)
    stage_clause = " AND stage IN ('p0','p1','p2')" if stage == "all" else " AND stage=?"
    params: list[Any] = list(kinds)
    if stage != "all":
        params.append(stage)
    db.execute("BEGIN IMMEDIATE")
    row = db.execute(
        f"""SELECT * FROM jobs WHERE status='pending'
            AND kind IN ({placeholders}){stage_clause}
            ORDER BY CASE stage WHEN 'p0' THEN 0 WHEN 'p1' THEN 1 WHEN 'p2' THEN 2 ELSE 3 END,
              CASE kind WHEN 'detail' THEN 0 WHEN 'search' THEN 1 WHEN 'replies' THEN 2 WHEN 'thread' THEN 3 ELSE 4 END,
              start_date,label,created_at LIMIT 1""",
        params,
    ).fetchone()
    if row is None:
        db.commit()
        return None
    db.execute(
        "UPDATE jobs SET status='running',run_id=?,updated_at=?,error=NULL,warning=NULL WHERE job_key=?",
        (run_id, utc_now(), row["job_key"]),
    )
    db.execute("UPDATE runs SET jobs_started=jobs_started+1 WHERE run_id=?", (run_id,))
    db.commit()
    return db.execute("SELECT * FROM jobs WHERE job_key=?", (row["job_key"],)).fetchone()


def _job_dates(row: sqlite3.Row) -> tuple[date | None, date | None]:
    start = date.fromisoformat(row["start_date"]) if row["start_date"] else None
    end = date.fromisoformat(row["end_date_exclusive"]) if row["end_date_exclusive"] else None
    return start, end


def _raw_generator(api: Any, row: sqlite3.Row, limit: int) -> tuple[AsyncIterator[Any], str]:
    cursor = row["cursor"]
    kv = {"cursor": cursor} if cursor else {}
    if row["kind"] == "search":
        kv["product"] = row["product"] or "Latest"
        return api.search_raw(row["query"], limit=limit, kv=kv), "Bottom"
    if row["kind"] == "replies":
        return api.tweet_replies_raw(int(row["seed_post_id"]), limit=limit, kv=kv), "ShowMoreThreads"
    if row["kind"] == "thread":
        return api.tweet_thread_raw(int(row["seed_post_id"]), limit=limit, kv=kv), "Bottom"
    raise ValueError(f"no paginated generator for {row['kind']}")


def _limits(cfg: dict[str, Any], kind: str) -> int:
    if kind == "replies":
        return int(cfg["reply_limit"])
    if kind == "thread":
        return int(cfg["thread_limit"])
    return int(cfg["per_window_limit"])


def _account_failure_status(account_db: Path, endpoint: str) -> tuple[str, str]:
    if not account_db.exists():
        return "auth_error", "account_db_missing"
    queue = endpoint or "SearchTimeline"
    with sqlite3.connect(account_db) as db:
        active = db.execute("SELECT COUNT(*) FROM accounts WHERE active=1").fetchone()[0]
        if active == 0:
            return "auth_error", "no_active_accounts"
        locked = db.execute(
            """SELECT COUNT(*) FROM accounts WHERE active=1
               AND json_extract(locks, ?) IS NOT NULL
               AND json_extract(locks, ?) > datetime('now')""",
            (f'$."{queue}"', f'$."{queue}"'),
        ).fetchone()[0]
    if locked >= active:
        return "rate_limited", "all_accounts_locked_for_endpoint"
    return "partial", "no_account_available"


def _split_search_job(db: sqlite3.Connection, cfg: dict[str, Any], row: sqlite3.Row) -> str:
    start, end = _job_dates(row)
    if start is None or end is None or (end - start).days <= 1:
        update_job(
            db, row["job_key"], "saturated", stop_reason="single_day_local_limit",
            warning="Single-day window reached the local inspection threshold; coverage may be incomplete.",
            completed=True, run_id=row["run_id"],
        )
        return "saturated"
    midpoint = start + timedelta(days=max(1, (end - start).days // 2))
    suffix = DATE_SUFFIX.search(row["query"] or "")
    base = (row["query"][: suffix.start()] if suffix else row["query"]).strip()
    for child_start, child_end in ((start, midpoint), (midpoint, end)):
        exact = f"{base} since:{child_start} until:{child_end}"
        make_job(
            db, "search", row["label"], exact, child_start, child_end,
            cfg=cfg, window_id=row["window_id"], product=row["product"], stage=row["stage"],
            mode=row["mode"], endpoint=row["endpoint"], seed_post_id=row["seed_post_id"],
            conversation_id=row["conversation_id"], parent_job_key=row["job_key"],
        )
    update_job(
        db, row["job_key"], "split_parent", stop_reason="local_limit_auto_split",
        warning="Window reached local threshold and was split into smaller half-open windows.",
        completed=True, run_id=row["run_id"],
    )
    return "split_parent"


def _enqueue_quote_search_for_seed(
    db: sqlite3.Connection,
    cfg: dict[str, Any],
    row: sqlite3.Row,
    username: str | None,
) -> None:
    """Create a verifiable URL search only after the seed author's handle is observed."""
    if not username or not row["seed_post_id"] or row["parent_job_key"]:
        return
    start, end = _job_dates(row)
    if start is None or end is None:
        return
    base = f"url:x.com/{username}/status/{row['seed_post_id']}"
    exact = f"{base} since:{start} until:{end}"
    make_job(
        db, "search", f"{row['label']}:quotes", exact, start, end,
        cfg=cfg, window_id=row["window_id"], product="Latest", stage=row["stage"],
        mode="quote_url_search", endpoint="SearchTimeline", seed_post_id=row["seed_post_id"],
        conversation_id=row["conversation_id"], parent_job_key=row["job_key"],
    )


async def process_job(
    api: Any,
    db: sqlite3.Connection,
    cfg: dict[str, Any],
    row: sqlite3.Row,
    *,
    deadline: float | None,
) -> str:
    from twscrape.models import parse_tweet, parse_tweets

    run_token = ACTIVE_RUN_ID.set(row["run_id"])
    job_token = ACTIVE_JOB_KEY.set(row["job_key"])
    endpoint_token = ACTIVE_ENDPOINT.set(row["endpoint"] or "unknown")
    deadline_token = ACTIVE_DEADLINE.set(deadline)
    start, end = _job_dates(row)
    limit = _limits(cfg, row["kind"])
    raw_count = int(row["raw_count"] or 0)
    valid_count = int(row["valid_count"] or 0)
    page_count = int(row["page_count"] or 0)
    seen = {x[0] for x in db.execute("SELECT DISTINCT post_id FROM retrieval_hits WHERE job_key=?", (row["job_key"],))}
    rank = len(seen)
    last_cursor = row["cursor"]
    new_pages = 0
    meta = {
        "query": row["query"], "query_version": row["query_version"],
        "window_start": row["start_date"], "window_end_exclusive": row["end_date_exclusive"],
        "seed_post_id": row["seed_post_id"], "mode": row["mode"], "product": row["product"],
        "cursor": last_cursor,
    }
    meta_token = ACTIVE_REQUEST_META.set(meta)
    try:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeBudgetExceeded("time budget reached before job start")
        if row["kind"] == "search" and raw_count >= limit:
            return _split_search_job(db, cfg, row)
        if row["kind"] == "detail":
            response = await api.tweet_details_raw(int(row["seed_post_id"]))
            if response is None:
                update_job(
                    db, row["job_key"], "empty_unverified", raw_count=raw_count,
                    unique_count=len(seen), valid_count=valid_count, stop_reason="no_response",
                    warning="No detail response; this does not prove the post never existed.",
                    run_id=row["run_id"], completed=True,
                )
                return "empty_unverified"
            response_id = getattr(response, "_who_raw_response_id", None)
            try:
                tweet = parse_tweet(response, int(row["seed_post_id"]))
            except Exception as exc:
                raise ParsingFailure(str(exc)) from exc
            if tweet is None:
                update_job(
                    db, row["job_key"], "empty_unverified", raw_count=raw_count,
                    unique_count=len(seen), valid_count=valid_count, stop_reason="detail_not_found",
                    warning="Detail endpoint returned no parseable post.", run_id=row["run_id"], completed=True,
                )
                return "empty_unverified"
            raw_count += 1
            rank += 1
            in_window = record_post(
                db, tweet, row["job_key"], start, end, run_id=row["run_id"],
                response_id=response_id, result_rank=rank, acquisition_use="context_fetch",
                seed_post_id=row["seed_post_id"],
            )
            valid_count += int(in_window is True)
            seen.add(str(tweet.id))
            db.commit()
            _enqueue_quote_search_for_seed(db, cfg, row, getattr(getattr(tweet, "user", None), "username", None))
            enqueue_missing_context(db, cfg, row)
            update_job(
                db, row["job_key"], "complete", raw_count=raw_count, unique_count=len(seen),
                valid_count=valid_count, stop_reason="endpoint_exhausted", cursor=None,
                page_count=page_count + 1, run_id=row["run_id"], completed=True,
            )
            return "complete"

        remaining_limit = max(1, limit - raw_count)
        generator, cursor_type = _raw_generator(api, row, remaining_limit)
        async with aclosing(generator) as pages:
            async for response in pages:
                new_pages += 1
                page_count += 1
                if deadline is not None and time.monotonic() >= deadline:
                    update_job(
                        db, row["job_key"], "partial", raw_count=raw_count,
                        unique_count=len(seen), valid_count=valid_count, stop_reason="time_budget",
                        cursor=last_cursor, page_count=page_count - 1, run_id=row["run_id"],
                    )
                    return "partial"
                response_id = getattr(response, "_who_raw_response_id", None)
                try:
                    tweets = list(parse_tweets(response, -1))
                    obj = response.json()
                    cursor_out = api._get_cursor(obj, cursor_type)
                except Exception as exc:
                    raise ParsingFailure(str(exc)) from exc
                if response_id:
                    db.execute("UPDATE raw_responses SET cursor_out=? WHERE response_id=?", (cursor_out, response_id))
                for tweet in tweets:
                    raw_count += 1
                    post_id = str(tweet.id)
                    if post_id not in seen:
                        rank += 1
                    use = "topic_search" if row["kind"] == "search" else "thread_context"
                    in_window = record_post(
                        db, tweet, row["job_key"], start, end, run_id=row["run_id"],
                        response_id=response_id, result_rank=rank, acquisition_use=use,
                        seed_post_id=row["seed_post_id"],
                    )
                    valid_count += int(in_window is True and post_id not in seen)
                    seen.add(post_id)
                last_cursor = cursor_out
                meta["cursor"] = last_cursor
                db.execute(
                    """UPDATE jobs SET raw_count=?,unique_count=?,valid_count=?,cursor=?,
                       page_count=?,updated_at=? WHERE job_key=?""",
                    (raw_count, len(seen), valid_count, last_cursor, page_count, utc_now(), row["job_key"]),
                )
                db.commit()
                if raw_count >= limit:
                    break
        enqueue_missing_context(db, cfg, row)
        final_raw_cursor = db.execute(
            """SELECT cursor_out,cursor_in FROM raw_responses
               WHERE run_id=? AND job_key=? AND http_status IS NOT NULL
               ORDER BY response_id DESC LIMIT 1""",
            (row["run_id"], row["job_key"]),
        ).fetchone()
        if final_raw_cursor:
            last_cursor = final_raw_cursor["cursor_out"] or final_raw_cursor["cursor_in"] or last_cursor
        requests = db.execute("SELECT COUNT(*) FROM raw_responses WHERE job_key=?", (row["job_key"],)).fetchone()[0]
        if raw_count >= limit:
            if row["kind"] == "search":
                return _split_search_job(db, cfg, db.execute("SELECT * FROM jobs WHERE job_key=?", (row["job_key"],)).fetchone())
            update_job(
                db, row["job_key"], "saturated", raw_count=raw_count, unique_count=len(seen),
                valid_count=valid_count, stop_reason="local_limit", cursor=last_cursor,
                page_count=page_count, request_count=requests,
                warning="Local reply/thread threshold reached; visible discussion may be incomplete.",
                run_id=row["run_id"], completed=True,
            )
            return "saturated"
        if new_pages == 0 and raw_count == 0:
            update_job(
                db, row["job_key"], "empty_unverified", raw_count=0, unique_count=0,
                valid_count=0, stop_reason="empty_response", cursor=last_cursor,
                page_count=page_count, request_count=requests,
                warning="Empty result is unverified and is not evidence of zero matching posts.",
                run_id=row["run_id"], completed=True,
            )
            return "empty_unverified"
        if last_cursor is not None:
            update_job(
                db, row["job_key"], "partial", raw_count=raw_count, unique_count=len(seen),
                valid_count=valid_count, stop_reason="pagination_stalled_or_unresolved_cursor",
                cursor=last_cursor, page_count=page_count, request_count=requests,
                warning="Generator stopped with a non-null cursor; not marked complete.",
                run_id=row["run_id"],
            )
            return "partial"
        update_job(
            db, row["job_key"], "complete", raw_count=raw_count, unique_count=len(seen),
            valid_count=valid_count, stop_reason="endpoint_exhausted", cursor=None,
            page_count=page_count, request_count=requests, run_id=row["run_id"], completed=True,
        )
        return "complete"
    except TimeBudgetExceeded as exc:
        update_job(
            db, row["job_key"], "partial", raw_count=raw_count, unique_count=len(seen),
            valid_count=valid_count, stop_reason="time_budget", cursor=last_cursor,
            page_count=page_count, error=redact_error(exc), run_id=row["run_id"],
        )
        return "partial"
    except ParsingFailure as exc:
        update_job(
            db, row["job_key"], "parse_error", raw_count=raw_count, unique_count=len(seen),
            valid_count=valid_count, stop_reason="parse_failure", cursor=last_cursor,
            page_count=page_count, error=redact_error(exc), run_id=row["run_id"],
        )
        return "parse_error"
    except Exception as exc:
        from twscrape import NoAccountError
        if isinstance(exc, NoAccountError):
            recent_errors = [
                x[0] or "" for x in db.execute(
                    """SELECT error FROM raw_responses
                       WHERE run_id=? AND job_key=? AND error IS NOT NULL ORDER BY response_id""",
                    (row["run_id"], row["job_key"]),
                )
            ]
            if recent_errors and all(
                value.startswith(("ConnectError:", "NetworkError:")) for value in recent_errors
            ):
                status, reason, return_status = (
                    "partial", "transport_error_accounts_cooling", "transport_error"
                )
            else:
                account_db = resolve_from_config(cfg, cfg["account_db"])
                status, reason = _account_failure_status(account_db, row["endpoint"] or "")
                return_status = status
        else:
            status, reason = "partial", "request_or_runtime_error"
            return_status = status
        update_job(
            db, row["job_key"], status, raw_count=raw_count, unique_count=len(seen),
            valid_count=valid_count, stop_reason=reason, cursor=last_cursor,
            page_count=page_count, error=f"{type(exc).__name__}: {redact_error(exc)}",
            run_id=row["run_id"],
        )
        return return_status
    finally:
        ACTIVE_REQUEST_META.reset(meta_token)
        ACTIVE_DEADLINE.reset(deadline_token)
        ACTIVE_ENDPOINT.reset(endpoint_token)
        ACTIVE_JOB_KEY.reset(job_token)
        ACTIVE_RUN_ID.reset(run_token)


async def run_collection(
    cfg: dict[str, Any],
    db: sqlite3.Connection,
    *,
    command: str,
    mode: str,
    stage: str,
    product: str,
    concurrency: int,
    max_jobs: int,
    max_minutes: float,
    retry_empty: bool,
) -> tuple[str, str]:
    from twscrape import API, set_log_level
    from twscrape.logger import logger as twscrape_logger

    scheduler = cfg["scheduler"]
    if not 1 <= concurrency <= int(scheduler["max_concurrency"]):
        raise ValueError(f"concurrency must be 1..{scheduler['max_concurrency']}")
    account_db = resolve_from_config(cfg, cfg["account_db"])
    if not account_db.exists():
        raise FileNotFoundError(f"account database not found: {account_db}")
    prepare_jobs_for_run(db, command=command, stage=stage, mode=mode, retry_empty=retry_empty)
    args = {
        "mode": mode, "stage": stage, "product": product, "concurrency": concurrency,
        "max_jobs": max_jobs, "max_minutes": max_minutes, "retry_empty": retry_empty,
    }
    run_id = start_run(db, cfg, command=command, mode=mode, stage=stage, product=product, args=args)
    # twscrape warning strings contain account usernames. The collector records
    # credential-free aliases and structured errors itself, so suppress the
    # library sink for the duration of a research run.
    set_log_level("ERROR")
    twscrape_logger.disable("twscrape")
    timeout_restore = install_httpx_timeout_patch(float(scheduler.get("http_timeout_seconds", 30)))
    api = API(
        str(account_db), raise_when_no_account=True,
        wait_timeout=float(scheduler["account_wait_timeout_seconds"]),
        wait_interval=float(scheduler["account_wait_poll_seconds"]),
    )
    throttle = RequestThrottle(
        db, float(scheduler["min_request_interval_seconds"]),
        float(scheduler["rate_limit_reserve_fraction"]),
    )
    restore = install_request_hook(db, throttle)
    deadline = time.monotonic() + max_minutes * 60 if max_minutes > 0 else None
    claim_lock = asyncio.Lock()
    state = {"claimed": 0, "finished": 0, "stop_reason": None}
    stop_event = asyncio.Event()

    async def claim() -> sqlite3.Row | None:
        async with claim_lock:
            if stop_event.is_set():
                return None
            if deadline is not None and time.monotonic() >= deadline:
                state["stop_reason"] = "time_budget"
                stop_event.set()
                return None
            if max_jobs and state["claimed"] >= max_jobs:
                state["stop_reason"] = "max_jobs"
                stop_event.set()
                return None
            row = claim_next_job(db, run_id=run_id, stage=stage, mode=mode)
            if row is not None:
                state["claimed"] += 1
            return row

    async def worker() -> None:
        while not stop_event.is_set():
            row = await claim()
            if row is None:
                return
            try:
                if deadline is None:
                    status = await process_job(api, db, cfg, row, deadline=deadline)
                else:
                    remaining = max(0.01, deadline - time.monotonic())
                    status = await asyncio.wait_for(
                        process_job(api, db, cfg, row, deadline=deadline), timeout=remaining
                    )
            except TimeoutError:
                current = db.execute("SELECT * FROM jobs WHERE job_key=?", (row["job_key"],)).fetchone()
                update_job(
                    db, row["job_key"], "partial",
                    raw_count=int(current["raw_count"] or 0),
                    unique_count=int(current["unique_count"] or 0),
                    valid_count=int(current["valid_count"] or 0),
                    stop_reason="hard_time_budget", cursor=current["cursor"],
                    page_count=int(current["page_count"] or 0), run_id=run_id,
                )
                status = "time_budget"
            state["finished"] += 1
            db.execute("UPDATE runs SET jobs_finished=jobs_finished+1 WHERE run_id=?", (run_id,))
            db.commit()
            if status in {"rate_limited", "auth_error", "transport_error"}:
                state["stop_reason"] = "accounts_unavailable"
                stop_event.set()
            elif status == "time_budget":
                state["stop_reason"] = "time_budget"
                stop_event.set()

    try:
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        pending = db.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='pending' "
            + ("" if stage == "all" else "AND stage=? ")
            + f"AND kind IN ({','.join('?' for _ in _allowed_kinds(mode))})",
            ([] if stage == "all" else [stage]) + list(_allowed_kinds(mode)),
        ).fetchone()[0]
        final_status = "complete" if pending == 0 and not state["stop_reason"] else f"stopped:{state['stop_reason'] or 'pending_jobs'}"
        finish_run(db, run_id, final_status)
        return run_id, final_status
    except Exception as exc:
        finish_run(db, run_id, "failed", f"{type(exc).__name__}: {redact_error(exc)}")
        raise
    finally:
        restore()
        timeout_restore()
        twscrape_logger.enable("twscrape")
