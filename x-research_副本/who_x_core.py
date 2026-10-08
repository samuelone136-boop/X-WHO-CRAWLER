"""Core configuration, schema, persistence, export, and audit helpers."""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc
SCHEMA_VERSION = 2
COLLECTOR_VERSION = "2.0.0"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def config_sha(cfg: dict[str, Any]) -> str:
    return sha256_text(json_dumps(cfg))


def twscrape_version() -> str:
    try:
        return importlib.metadata.version("twscrape")
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def load_config(filename: str | Path) -> dict[str, Any]:
    path = Path(filename).expanduser().resolve()
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["_config_path"] = str(path)
    for key in ("platform", "query_version", "query_registry", "windows", "scheduler"):
        if key not in cfg:
            raise ValueError(f"missing config key: {key}")
    for window_id, window in cfg["windows"].items():
        start = date.fromisoformat(window["start_date"])
        end = date.fromisoformat(window["end_date_exclusive"])
        if start >= end:
            raise ValueError(f"invalid half-open window {window_id}: [{start}, {end})")
    scheduler = cfg["scheduler"]
    concurrency = int(scheduler["concurrency"])
    max_concurrency = int(scheduler["max_concurrency"])
    if not 1 <= concurrency <= max_concurrency <= 3:
        raise ValueError("scheduler concurrency must be between 1 and 3")
    if float(scheduler["min_request_interval_seconds"]) < 10:
        raise ValueError("min_request_interval_seconds must be at least 10")
    if float(scheduler.get("http_timeout_seconds", 30)) < 10:
        raise ValueError("http_timeout_seconds must be at least 10")
    reserve = float(scheduler["rate_limit_reserve_fraction"])
    if not 0 <= reserve < 1:
        raise ValueError("rate_limit_reserve_fraction must be in [0,1)")
    return cfg


def resolve_from_config(cfg: dict[str, Any], value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(cfg["_config_path"]).parent / path
    return path.resolve()


def get_paths(cfg: dict[str, Any]) -> tuple[Path, Path]:
    out = resolve_from_config(cfg, cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    return out, out / "research.sqlite"


def segments(start: date, end: date, days: int) -> Iterable[tuple[date, date]]:
    if days < 1:
        raise ValueError("days must be positive")
    current = start
    while current < end:
        following = min(end, current + timedelta(days=days))
        yield current, following
        current = following


@dataclass(frozen=True)
class QuerySpec:
    query_id: str
    window_id: str
    text: str
    full_text: str
    stage: str
    product: str
    source_kind: str


QUERY_ROW = re.compile(
    r"^\|\s*([A-Z0-9]+-\d+)\s*\|\s*(W\d+)\s*\|\s*`(.+?)`\s*\|$"
)
TEMPLATE_ROW = re.compile(r"^\|\s*(D\d+)\s*\|\s*`(.+?)`\s*\|")
DATE_SUFFIX = re.compile(
    r"\s+since:(\d{4}-\d{2}-\d{2})\s+until:(\d{4}-\d{2}-\d{2})\s*$"
)


def query_stage(query_id: str) -> str:
    if query_id.startswith(("F20-", "F22-", "S24-", "O20-", "O22-", "O24-")):
        return "p0"
    if query_id.startswith(("E24-", "L20-", "L22-", "L24-")):
        return "p1"
    if query_id.startswith(("G24-", "M24-", "MF-")):
        return "p2"
    raise ValueError(f"unrecognized query priority for {query_id}")


def load_query_registry(cfg: dict[str, Any]) -> tuple[list[QuerySpec], list[dict[str, str]]]:
    path = resolve_from_config(cfg, cfg["query_registry"])
    if not path.exists():
        raise FileNotFoundError(f"query registry is missing: {path}")
    queries: list[QuerySpec] = []
    templates: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := QUERY_ROW.match(line):
            query_id, window_id, full_text = match.groups()
            if window_id not in cfg["windows"]:
                raise ValueError(f"{query_id} references unknown window {window_id}")
            suffix = DATE_SUFFIX.search(full_text)
            if not suffix:
                raise ValueError(f"{query_id} has no terminal since/until pair")
            expected = cfg["windows"][window_id]
            if (suffix.group(1), suffix.group(2)) != (
                expected["start_date"], expected["end_date_exclusive"]
            ):
                raise ValueError(f"{query_id}/{window_id} dates disagree with config")
            queries.append(
                QuerySpec(
                    query_id=query_id,
                    window_id=window_id,
                    text=full_text[: suffix.start()].strip(),
                    full_text=full_text,
                    stage=query_stage(query_id),
                    product=expected["product"],
                    source_kind="known_link" if query_id.startswith("L") else "keyword",
                )
            )
        elif match := TEMPLATE_ROW.match(line):
            templates.append({"id": match.group(1), "text": match.group(2)})
    expected_fixed = int(cfg.get("expected_fixed_query_rows", len(queries)))
    expected_dynamic = int(cfg.get("expected_dynamic_templates", len(templates)))
    if len(queries) != expected_fixed:
        raise ValueError(f"registry parsed {len(queries)} fixed rows; expected {expected_fixed}")
    if len(templates) != expected_dynamic:
        raise ValueError(f"registry parsed {len(templates)} templates; expected {expected_dynamic}")
    return queries, templates


def job_key(
    kind: str,
    label: str,
    start: date | str | None = None,
    end: date | str | None = None,
    *,
    query_text: str | None = None,
    query_version: str = "legacy",
    platform: str = "x",
    mode: str | None = None,
    seed_id: str | None = None,
    product: str = "Latest",
) -> str:
    identity = {
        "platform": platform,
        "kind": kind,
        "label": label,
        "query_text": query_text if query_text is not None else label,
        "query_version": query_version,
        "window_start": str(start) if start else None,
        "window_end_exclusive": str(end) if end else None,
        "seed_id": str(seed_id) if seed_id else None,
        "mode": mode or kind,
        "product": product,
    }
    return sha256_text(json_dumps(identity))[:32]


BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
  post_id TEXT PRIMARY KEY,
  published_at_utc TEXT,
  username TEXT,
  author_id TEXT,
  text TEXT,
  lang TEXT,
  like_count INTEGER,
  repost_count INTEGER,
  reply_count INTEGER,
  quote_count INTEGER,
  view_count INTEGER,
  conversation_id TEXT,
  reply_to_id TEXT,
  quoted_id TEXT,
  raw_json TEXT NOT NULL,
  first_retrieved_at TEXT NOT NULL,
  last_retrieved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  job_key TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  query TEXT,
  start_date TEXT,
  end_date_exclusive TEXT,
  status TEXT NOT NULL,
  raw_count INTEGER DEFAULT 0,
  unique_count INTEGER DEFAULT 0,
  valid_count INTEGER DEFAULT 0,
  warning TEXT,
  error TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hits (
  post_id TEXT NOT NULL,
  job_key TEXT NOT NULL,
  in_window INTEGER NOT NULL,
  found_at TEXT NOT NULL,
  PRIMARY KEY(post_id, job_key),
  FOREIGN KEY(post_id) REFERENCES posts(post_id),
  FOREIGN KEY(job_key) REFERENCES jobs(job_key)
);
CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(published_at_utc);
CREATE INDEX IF NOT EXISTS idx_hits_job ON hits(job_key);

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  command TEXT NOT NULL,
  mode TEXT,
  stage TEXT,
  product TEXT,
  config_sha256 TEXT NOT NULL,
  query_version TEXT NOT NULL,
  collector_version TEXT NOT NULL,
  twscrape_version TEXT NOT NULL,
  args_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL,
  jobs_started INTEGER NOT NULL DEFAULT 0,
  jobs_finished INTEGER NOT NULL DEFAULT 0,
  requests INTEGER NOT NULL DEFAULT 0,
  wait_seconds REAL NOT NULL DEFAULT 0,
  error TEXT
);
CREATE TABLE IF NOT EXISTS raw_responses (
  response_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  job_key TEXT,
  endpoint TEXT NOT NULL,
  request_method TEXT NOT NULL,
  request_json TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  received_at TEXT,
  http_status INTEGER,
  response_headers_json TEXT,
  response_body TEXT,
  response_sha256 TEXT,
  account_alias TEXT,
  cursor_in TEXT,
  cursor_out TEXT,
  error TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(job_key) REFERENCES jobs(job_key)
);
CREATE TABLE IF NOT EXISTS retrieval_hits (
  hit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL,
  job_key TEXT NOT NULL,
  run_id TEXT,
  response_id INTEGER,
  found_at TEXT NOT NULL,
  result_rank INTEGER,
  in_window INTEGER,
  acquisition_use TEXT NOT NULL,
  UNIQUE(post_id, job_key, response_id),
  FOREIGN KEY(post_id) REFERENCES posts(post_id),
  FOREIGN KEY(job_key) REFERENCES jobs(job_key),
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(response_id) REFERENCES raw_responses(response_id)
);
CREATE TABLE IF NOT EXISTS post_relations (
  relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_post_id TEXT NOT NULL,
  to_post_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  seed_post_id TEXT,
  job_key TEXT,
  first_observed_at TEXT NOT NULL,
  UNIQUE(from_post_id, to_post_id, relation_type, seed_post_id, job_key)
);
CREATE TABLE IF NOT EXISTS user_snapshots (
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  post_id TEXT,
  run_id TEXT,
  job_key TEXT,
  response_id INTEGER,
  retrieved_at TEXT NOT NULL,
  username TEXT,
  display_name TEXT,
  description TEXT,
  location TEXT,
  followers_count INTEGER,
  following_count INTEGER,
  statuses_count INTEGER,
  verified INTEGER,
  protected INTEGER,
  profile_json TEXT NOT NULL,
  UNIQUE(user_id, response_id)
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL,
  run_id TEXT,
  job_key TEXT,
  response_id INTEGER,
  retrieved_at TEXT NOT NULL,
  like_count INTEGER,
  repost_count INTEGER,
  reply_count INTEGER,
  quote_count INTEGER,
  view_count INTEGER,
  bookmark_count INTEGER,
  UNIQUE(post_id, response_id)
);
CREATE TABLE IF NOT EXISTS annotations (
  annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL,
  study_id TEXT NOT NULL DEFAULT 'unassigned',
  coder_id TEXT NOT NULL DEFAULT 'legacy_csv',
  codebook_version TEXT NOT NULL DEFAULT 'unversioned',
  variable TEXT NOT NULL,
  value TEXT,
  evidence_span TEXT,
  note TEXT,
  coded_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(post_id, study_id, coder_id, codebook_version, variable)
);
CREATE TABLE IF NOT EXISTS corpus_membership (
  post_id TEXT NOT NULL,
  study_id TEXT NOT NULL,
  stratum TEXT NOT NULL,
  inclusion_rule TEXT,
  inclusion_status TEXT NOT NULL DEFAULT 'candidate',
  recorded_at TEXT NOT NULL,
  PRIMARY KEY(post_id, study_id, stratum)
);
CREATE TABLE IF NOT EXISTS job_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  job_key TEXT,
  event_at TEXT NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT,
  detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS throttle_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  job_key TEXT,
  account_alias TEXT,
  endpoint TEXT,
  event_at TEXT NOT NULL,
  reason TEXT NOT NULL,
  wait_seconds REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_job ON raw_responses(job_key, response_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_post ON retrieval_hits(post_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_job ON retrieval_hits(job_key);
CREATE INDEX IF NOT EXISTS idx_relations_to ON post_relations(to_post_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_metrics_post ON metric_snapshots(post_id, retrieved_at);
CREATE INDEX IF NOT EXISTS idx_users_user ON user_snapshots(user_id, retrieved_at);
"""


POST_COLUMNS: dict[str, str] = {
    "source_url": "TEXT",
    "item_type": "TEXT NOT NULL DEFAULT 'x_post'",
    "entities_json": "TEXT",
    "links_json": "TEXT",
    "media_json": "TEXT",
    "acquisition_use": "TEXT NOT NULL DEFAULT 'topic_search'",
}

JOB_COLUMNS: dict[str, str] = {
    "platform": "TEXT NOT NULL DEFAULT 'x'",
    "query_version": "TEXT NOT NULL DEFAULT 'legacy_v1'",
    "query_hash": "TEXT",
    "window_id": "TEXT",
    "product": "TEXT NOT NULL DEFAULT 'Latest'",
    "stage": "TEXT NOT NULL DEFAULT 'legacy'",
    "mode": "TEXT",
    "endpoint": "TEXT",
    "seed_post_id": "TEXT",
    "conversation_id": "TEXT",
    "run_id": "TEXT",
    "parent_job_key": "TEXT",
    "cursor": "TEXT",
    "page_count": "INTEGER NOT NULL DEFAULT 0",
    "request_count": "INTEGER NOT NULL DEFAULT 0",
    "stop_reason": "TEXT",
    "created_at": "TEXT",
    "completed_at": "TEXT",
    "config_sha256": "TEXT",
}


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _ensure_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _column_names(db, table)
    for name, declaration in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _migrate_legacy(db: sqlite3.Connection) -> None:
    now = utc_now()
    for row in db.execute("SELECT job_key, query, kind, updated_at FROM jobs").fetchall():
        query = row["query"] or ""
        endpoint = "SearchTimeline" if row["kind"] == "search" else "TweetDetail"
        db.execute(
            """UPDATE jobs SET query_hash=COALESCE(query_hash,?), mode=COALESCE(mode,kind),
               endpoint=COALESCE(endpoint,?), created_at=COALESCE(created_at,updated_at,?)
               WHERE job_key=?""",
            (sha256_text(query), endpoint, now, row["job_key"]),
        )
    db.execute(
        """INSERT OR IGNORE INTO retrieval_hits
           (post_id,job_key,run_id,response_id,found_at,result_rank,in_window,acquisition_use)
           SELECT h.post_id,h.job_key,NULL,NULL,h.found_at,NULL,h.in_window,'legacy_v1'
           FROM hits h JOIN jobs j ON j.job_key=h.job_key
           WHERE j.stage='legacy'
             AND NOT EXISTS (
             SELECT 1 FROM retrieval_hits r
             WHERE r.post_id=h.post_id AND r.job_key=h.job_key AND r.acquisition_use='legacy_v1'
           )"""
    )
    db.execute(
        """INSERT OR IGNORE INTO metric_snapshots
           (post_id,retrieved_at,like_count,repost_count,reply_count,quote_count,view_count)
           SELECT post_id,last_retrieved_at,like_count,repost_count,reply_count,quote_count,view_count
           FROM posts p
           WHERE EXISTS (
             SELECT 1 FROM hits h JOIN jobs j ON j.job_key=h.job_key
             WHERE h.post_id=p.post_id AND j.stage='legacy'
           )
             AND NOT EXISTS (
             SELECT 1 FROM metric_snapshots m
             WHERE m.post_id=p.post_id AND m.response_id IS NULL AND m.retrieved_at=p.last_retrieved_at
           )"""
    )
    for post in db.execute(
        """SELECT post_id,author_id,username,raw_json,last_retrieved_at,
                  reply_to_id,quoted_id,conversation_id FROM posts p
            WHERE EXISTS (
              SELECT 1 FROM hits h JOIN jobs j ON j.job_key=h.job_key
              WHERE h.post_id=p.post_id AND j.stage='legacy'
            )"""
    ).fetchall():
        if post["author_id"] and not db.execute(
            """SELECT 1 FROM user_snapshots
               WHERE user_id=? AND post_id=? AND response_id IS NULL LIMIT 1""",
            (post["author_id"], post["post_id"]),
        ).fetchone():
            try:
                raw = json.loads(post["raw_json"])
            except (TypeError, json.JSONDecodeError):
                raw = {}
            user = raw.get("user") if isinstance(raw, dict) else {}
            user = user if isinstance(user, dict) else {}
            db.execute(
                """INSERT INTO user_snapshots
                   (user_id,post_id,retrieved_at,username,display_name,description,location,
                    followers_count,following_count,statuses_count,verified,protected,profile_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    post["author_id"], post["post_id"], post["last_retrieved_at"],
                    user.get("username", post["username"]), user.get("displayname"),
                    user.get("rawDescription"), user.get("location"), user.get("followersCount"),
                    user.get("friendsCount"), user.get("statusesCount"), user.get("verified"),
                    user.get("protected"), json_dumps(user),
                ),
            )
        legacy_relations = (
            (post["reply_to_id"], "reply_to"),
            (post["quoted_id"], "quotes"),
            (
                post["conversation_id"] if post["conversation_id"] != post["post_id"] else None,
                "conversation_root",
            ),
        )
        for target, relation_type in legacy_relations:
            if target and not db.execute(
                """SELECT 1 FROM post_relations
                   WHERE from_post_id=? AND to_post_id=? AND relation_type=?
                     AND seed_post_id IS NULL AND job_key IS NULL LIMIT 1""",
                (post["post_id"], str(target), relation_type),
            ).fetchone():
                db.execute(
                    """INSERT OR IGNORE INTO post_relations
                       (from_post_id,to_post_id,relation_type,seed_post_id,job_key,first_observed_at)
                       VALUES(?,?,?,?,?,?)""",
                    (post["post_id"], str(target), relation_type, None, None, post["last_retrieved_at"]),
                )
    db.execute(
        """UPDATE jobs SET status='partial',stop_reason='transport_error_accounts_cooling',
                          updated_at=?
           WHERE status='rate_limited'
             AND EXISTS (
               SELECT 1 FROM raw_responses r
               WHERE r.job_key=jobs.job_key
                 AND (r.error LIKE 'ConnectError:%' OR r.error LIKE 'NetworkError:%')
             )
             AND NOT EXISTS (
               SELECT 1 FROM raw_responses r
               WHERE r.job_key=jobs.job_key AND r.error IS NOT NULL
                 AND r.error NOT LIKE 'ConnectError:%' AND r.error NOT LIKE 'NetworkError:%'
             )""",
        (now,),
    )
    legacy_posts_sql = "SELECT h.post_id FROM hits h JOIN jobs j ON j.job_key=h.job_key WHERE j.stage='legacy'"
    db.execute(
        "DELETE FROM retrieval_hits WHERE acquisition_use='legacy_v1' "
        "AND job_key IN (SELECT job_key FROM jobs WHERE stage!='legacy')"
    )
    db.execute(
        f"DELETE FROM metric_snapshots WHERE response_id IS NULL AND post_id NOT IN ({legacy_posts_sql})"
    )
    db.execute(
        f"DELETE FROM user_snapshots WHERE response_id IS NULL AND job_key IS NULL "
        f"AND post_id NOT IN ({legacy_posts_sql})"
    )
    db.execute(
        f"DELETE FROM post_relations WHERE seed_post_id IS NULL AND job_key IS NULL "
        f"AND from_post_id NOT IN ({legacy_posts_sql})"
    )
    db.execute(
        "INSERT INTO schema_meta(key,value,updated_at) VALUES('schema_version',?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
        (str(SCHEMA_VERSION), now),
    )


def open_db(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(Path(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    with db:
        db.executescript(BASE_SCHEMA)
        _ensure_columns(db, "posts", POST_COLUMNS)
        _ensure_columns(db, "jobs", JOB_COLUMNS)
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_stage ON jobs(status, stage, kind)")
        _migrate_legacy(db)
    return db


def backup_database(source: Path, destination: Path | None = None) -> Path:
    source = source.resolve()
    if destination is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = source.parent / "backups" / f"{source.stem}_{stamp}.sqlite"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    with sqlite3.connect(destination) as check:
        result = check.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise RuntimeError(f"backup failed quick_check: {result}")
    return destination


def post_date(tweet: Any) -> datetime | None:
    value = getattr(tweet, "date", None)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default) if obj is not None else default


def _snapshot_user(
    db: sqlite3.Connection,
    tweet: Any,
    *,
    post_id: str,
    retrieved: str,
    run_id: str | None,
    job_key_value: str,
    response_id: int | None,
) -> None:
    user = _attr(tweet, "user")
    if user is None or _attr(user, "id") is None:
        return
    profile = user.dict() if hasattr(user, "dict") else vars(user)
    db.execute(
        """INSERT OR IGNORE INTO user_snapshots
           (user_id,post_id,run_id,job_key,response_id,retrieved_at,username,display_name,
            description,location,followers_count,following_count,statuses_count,verified,
            protected,profile_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(user.id), post_id, run_id, job_key_value, response_id, retrieved,
            _attr(user, "username"), _attr(user, "displayname"), _attr(user, "rawDescription"),
            _attr(user, "location"), _attr(user, "followersCount"), _attr(user, "friendsCount"),
            _attr(user, "statusesCount"), _attr(user, "verified"), _attr(user, "protected"),
            json_dumps(profile),
        ),
    )


def _snapshot_metrics(
    db: sqlite3.Connection,
    tweet: Any,
    *,
    post_id: str,
    retrieved: str,
    run_id: str | None,
    job_key_value: str,
    response_id: int | None,
) -> None:
    db.execute(
        """INSERT OR IGNORE INTO metric_snapshots
           (post_id,run_id,job_key,response_id,retrieved_at,like_count,repost_count,
            reply_count,quote_count,view_count,bookmark_count)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            post_id, run_id, job_key_value, response_id, retrieved,
            _attr(tweet, "likeCount"), _attr(tweet, "retweetCount"),
            _attr(tweet, "replyCount"), _attr(tweet, "quoteCount"),
            _attr(tweet, "viewCount"), _attr(tweet, "bookmarkedCount"),
        ),
    )


def record_post(
    db: sqlite3.Connection,
    tweet: Any,
    job_key_value: str,
    start: date | None,
    end: date | None,
    *,
    run_id: str | None = None,
    response_id: int | None = None,
    result_rank: int | None = None,
    acquisition_use: str = "topic_search",
    seed_post_id: str | None = None,
) -> bool | None:
    post_id = str(tweet.id)
    published = post_date(tweet)
    user = _attr(tweet, "user")
    quoted = _attr(tweet, "quotedTweet")
    reposted = _attr(tweet, "retweetedTweet")
    serialized = tweet.dict() if hasattr(tweet, "dict") else vars(tweet)
    retrieved = utc_now()
    in_window: bool | None = None
    if start is not None and end is not None:
        in_window = bool(published and start <= published.date() < end)
    reply_to = _attr(tweet, "inReplyToTweetId")
    conversation = _attr(tweet, "conversationId")
    quoted_id = _attr(quoted, "id")
    reposted_id = _attr(reposted, "id")
    item_type = "x_reply" if reply_to else "x_quote" if quoted_id else "x_repost" if reposted_id else "x_post"
    entities = {
        "hashtags": _attr(tweet, "hashtags", []),
        "cashtags": _attr(tweet, "cashtags", []),
        "mentioned_users": [x.dict() if hasattr(x, "dict") else vars(x) for x in _attr(tweet, "mentionedUsers", [])],
    }
    links = [x.dict() if hasattr(x, "dict") else vars(x) for x in _attr(tweet, "links", [])]
    media = _attr(tweet, "media")
    media_value = media.dict() if hasattr(media, "dict") else media
    db.execute(
        """INSERT INTO posts
           (post_id,published_at_utc,username,author_id,text,lang,like_count,repost_count,
            reply_count,quote_count,view_count,conversation_id,reply_to_id,quoted_id,
            raw_json,first_retrieved_at,last_retrieved_at,source_url,item_type,entities_json,
            links_json,media_json,acquisition_use)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(post_id) DO UPDATE SET
             published_at_utc=COALESCE(excluded.published_at_utc,posts.published_at_utc),
             username=COALESCE(excluded.username,posts.username),
             author_id=COALESCE(excluded.author_id,posts.author_id),
             text=COALESCE(excluded.text,posts.text),lang=COALESCE(excluded.lang,posts.lang),
             like_count=excluded.like_count,repost_count=excluded.repost_count,
             reply_count=excluded.reply_count,quote_count=excluded.quote_count,
             view_count=excluded.view_count,
             conversation_id=COALESCE(excluded.conversation_id,posts.conversation_id),
             reply_to_id=COALESCE(excluded.reply_to_id,posts.reply_to_id),
             quoted_id=COALESCE(excluded.quoted_id,posts.quoted_id),
             raw_json=excluded.raw_json,last_retrieved_at=excluded.last_retrieved_at,
             source_url=COALESCE(excluded.source_url,posts.source_url),
             item_type=excluded.item_type,entities_json=excluded.entities_json,
             links_json=excluded.links_json,media_json=excluded.media_json""",
        (
            post_id, published.isoformat() if published else None,
            _attr(user, "username"), str(_attr(user, "id")) if _attr(user, "id") is not None else None,
            _attr(tweet, "rawContent"), _attr(tweet, "lang"), _attr(tweet, "likeCount"),
            _attr(tweet, "retweetCount"), _attr(tweet, "replyCount"), _attr(tweet, "quoteCount"),
            _attr(tweet, "viewCount"), str(conversation) if conversation is not None else None,
            str(reply_to) if reply_to is not None else None,
            str(quoted_id) if quoted_id is not None else None,
            json_dumps(serialized), retrieved, retrieved, _attr(tweet, "url"), item_type,
            json_dumps(entities), json_dumps(links), json_dumps(media_value), acquisition_use,
        ),
    )
    db.execute(
        """INSERT OR IGNORE INTO retrieval_hits
           (post_id,job_key,run_id,response_id,found_at,result_rank,in_window,acquisition_use)
           VALUES(?,?,?,?,?,?,?,?)""",
        (post_id, job_key_value, run_id, response_id, retrieved, result_rank,
         None if in_window is None else int(in_window), acquisition_use),
    )
    db.execute(
        "INSERT OR IGNORE INTO hits(post_id,job_key,in_window,found_at) VALUES(?,?,?,?)",
        (post_id, job_key_value, int(bool(in_window)), retrieved),
    )
    _snapshot_user(
        db, tweet, post_id=post_id, retrieved=retrieved, run_id=run_id,
        job_key_value=job_key_value, response_id=response_id,
    )
    _snapshot_metrics(
        db, tweet, post_id=post_id, retrieved=retrieved, run_id=run_id,
        job_key_value=job_key_value, response_id=response_id,
    )
    relations = []
    if reply_to is not None:
        relations.append((str(reply_to), "reply_to"))
    if conversation is not None and str(conversation) != post_id:
        relations.append((str(conversation), "conversation_root"))
    if quoted_id is not None:
        relations.append((str(quoted_id), "quotes"))
    if reposted_id is not None:
        relations.append((str(reposted_id), "reposts"))
    for target, relation_type in relations:
        db.execute(
            """INSERT OR IGNORE INTO post_relations
               (from_post_id,to_post_id,relation_type,seed_post_id,job_key,first_observed_at)
               VALUES(?,?,?,?,?,?)""",
            (post_id, target, relation_type, seed_post_id, job_key_value, retrieved),
        )
    return in_window


def make_job(
    db: sqlite3.Connection,
    kind: str,
    label: str,
    query: str,
    start: date | None,
    end: date | None,
    *,
    cfg: dict[str, Any] | None = None,
    query_version: str | None = None,
    platform: str = "x",
    window_id: str | None = None,
    product: str = "Latest",
    stage: str = "p0",
    mode: str | None = None,
    endpoint: str | None = None,
    seed_post_id: str | None = None,
    conversation_id: str | None = None,
    parent_job_key: str | None = None,
) -> str:
    version = query_version or (cfg or {}).get("query_version", "legacy")
    platform_value = (cfg or {}).get("platform", platform)
    mode_value = mode or kind
    key = job_key(
        kind, label, start, end, query_text=query, query_version=version,
        platform=platform_value, mode=mode_value, seed_id=seed_post_id, product=product,
    )
    now = utc_now()
    db.execute(
        """INSERT OR IGNORE INTO jobs
           (job_key,kind,label,query,start_date,end_date_exclusive,status,updated_at,
            platform,query_version,query_hash,window_id,product,stage,mode,endpoint,
            seed_post_id,conversation_id,parent_job_key,created_at,config_sha256)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            key, kind, label, query, str(start) if start else None, str(end) if end else None,
            "pending", now, platform_value, version, sha256_text(query), window_id, product,
            stage, mode_value, endpoint, seed_post_id, conversation_id, parent_job_key,
            now, config_sha(cfg) if cfg else None,
        ),
    )
    db.commit()
    return key


def register_jobs(
    db: sqlite3.Connection,
    cfg: dict[str, Any],
    *,
    stage: str = "all",
    product: str = "Latest",
) -> dict[str, int]:
    queries, templates = load_query_registry(cfg)
    counts = {"search": 0, "seed": 0, "templates": len(templates), "disabled_dynamic": 0}
    allowed = {"p0", "p1", "p2"} if stage == "all" else {stage}
    for spec in queries:
        if spec.stage not in allowed:
            continue
        window = cfg["windows"][spec.window_id]
        start = date.fromisoformat(window["start_date"])
        end = date.fromisoformat(window["end_date_exclusive"])
        for segment_start, segment_end in segments(start, end, int(cfg["window_days"])):
            exact = f"{spec.text} since:{segment_start.isoformat()} until:{segment_end.isoformat()}"
            make_job(
                db, "search", spec.query_id, exact, segment_start, segment_end,
                cfg=cfg, window_id=spec.window_id, product=product, stage=spec.stage,
                mode="keyword_search" if spec.source_kind == "keyword" else "known_link_search",
                endpoint="SearchTimeline",
            )
            counts["search"] += 1
    for seed in cfg.get("seed_posts", []):
        seed_stage = seed.get("stage", "p1")
        if seed_stage not in allowed:
            continue
        window_id = seed.get("window")
        window = cfg["windows"].get(window_id, {})
        start = date.fromisoformat(window["start_date"]) if window else None
        end = date.fromisoformat(window["end_date_exclusive"]) if window else None
        for seed_mode in seed.get("modes", ["details", "replies", "thread"]):
            limit_kind = "detail" if seed_mode == "details" else seed_mode
            make_job(
                db, limit_kind, f"{seed['id']}:{seed_mode}",
                f"tweet_{seed_mode}:{seed['post_id']}", start, end,
                cfg=cfg, window_id=window_id, product="Latest", stage=seed_stage,
                mode="context_fetch", endpoint="TweetDetail", seed_post_id=str(seed["post_id"]),
            )
            counts["seed"] += 1
    for dynamic in cfg.get("dynamic_queries", []):
        text = dynamic.get("text", "")
        if not dynamic.get("enabled") or "{" in text or "}" in text:
            counts["disabled_dynamic"] += 1
            continue
        window_id = dynamic["window"]
        window = cfg["windows"][window_id]
        dynamic_stage = dynamic.get("stage", "p1")
        if dynamic_stage not in allowed:
            continue
        start = date.fromisoformat(window["start_date"])
        end = date.fromisoformat(window["end_date_exclusive"])
        for segment_start, segment_end in segments(start, end, int(cfg["window_days"])):
            exact = f"{text} since:{segment_start} until:{segment_end}"
            make_job(
                db, "search", dynamic["id"], exact, segment_start, segment_end,
                cfg=cfg, window_id=window_id, product=product, stage=dynamic_stage,
                mode="dynamic_search", endpoint="SearchTimeline",
            )
            counts["search"] += 1
    return counts


def enqueue_missing_context(
    db: sqlite3.Connection,
    cfg: dict[str, Any],
    source_job: sqlite3.Row,
) -> int:
    rows = db.execute(
        """SELECT DISTINCT r.to_post_id, r.relation_type
           FROM post_relations r LEFT JOIN posts p ON p.post_id=r.to_post_id
           WHERE r.job_key=? AND p.post_id IS NULL""",
        (source_job["job_key"],),
    ).fetchall()
    created = 0
    for row in rows:
        before = db.total_changes
        make_job(
            db, "detail", f"context:{row['relation_type']}:{row['to_post_id']}",
            f"tweet_details:{row['to_post_id']}", None, None, cfg=cfg,
            window_id=source_job["window_id"], product="Latest", stage=source_job["stage"],
            mode="context_fetch", endpoint="TweetDetail", seed_post_id=row["to_post_id"],
            parent_job_key=source_job["job_key"],
        )
        created += int(db.total_changes > before)
    return created


def update_job(
    db: sqlite3.Connection,
    key: str,
    status: str,
    raw_count: int | None = None,
    unique_count: int | None = None,
    valid_count: int | None = None,
    *,
    warning: str | None = None,
    error: str | None = None,
    stop_reason: str | None = None,
    cursor: str | None = None,
    page_count: int | None = None,
    request_count: int | None = None,
    run_id: str | None = None,
    completed: bool = False,
) -> None:
    now = utc_now()
    db.execute(
        """UPDATE jobs SET status=?,raw_count=COALESCE(?,raw_count),
           unique_count=COALESCE(?,unique_count),valid_count=COALESCE(?,valid_count),
           warning=?,error=?,stop_reason=?,cursor=?,page_count=COALESCE(?,page_count),
           request_count=COALESCE(?,request_count),run_id=COALESCE(?,run_id),
           completed_at=CASE WHEN ? THEN ? ELSE completed_at END,updated_at=?
           WHERE job_key=?""",
        (
            status, raw_count, unique_count, valid_count, warning, error, stop_reason,
            cursor, page_count, request_count, run_id, int(completed), now, now, key,
        ),
    )
    db.execute(
        "INSERT INTO job_events(run_id,job_key,event_at,event_type,status,detail_json) VALUES(?,?,?,?,?,?)",
        (run_id, key, now, "status", status, json_dumps({"stop_reason": stop_reason, "warning": warning, "error": error})),
    )
    db.commit()


def latest_annotations(db: sqlite3.Connection) -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    rows = db.execute(
        """SELECT a.* FROM annotations a JOIN (
             SELECT post_id,variable,MAX(updated_at) AS newest FROM annotations GROUP BY post_id,variable
           ) x ON x.post_id=a.post_id AND x.variable=a.variable AND x.newest=a.updated_at"""
    )
    for row in rows:
        values.setdefault(row["post_id"], {})[row["variable"]] = row["value"] or ""
    return values


def _read_existing_coding(path: Path) -> tuple[dict[str, dict[str, str]], list[str]]:
    if not path.exists():
        return {}, []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = {row.get("post_id", ""): row for row in reader if row.get("post_id")}
        return rows, list(reader.fieldnames or [])


def _atomic_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def export_data(cfg: dict[str, Any], db: sqlite3.Connection) -> Path:
    out, _ = get_paths(cfg)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    export_dir = out / "exports" / stamp
    export_dir.mkdir(parents=True, exist_ok=True)
    coding_path = out / "coding" / "master_posts.csv"
    old_rows, old_fields = _read_existing_coding(coding_path)
    generated = [
        "post_id", "published_at_utc", "username", "author_id", "text", "lang",
        "item_type", "source_url", "conversation_id", "reply_to_id", "quoted_id",
        "first_retrieved_at", "last_retrieved_at", "found_by", "source_modes",
        "matching_jobs", "in_any_core_window", "relevance_label", "notes",
    ]
    fields = generated + [name for name in old_fields if name not in generated]
    annotation_values = latest_annotations(db)
    rows = db.execute(
        """SELECT p.*,
           GROUP_CONCAT(DISTINCT j.label) AS found_by,
           GROUP_CONCAT(DISTINCT j.mode) AS source_modes,
           COUNT(DISTINCT h.job_key) AS matching_jobs,
           MAX(COALESCE(h.in_window,0)) AS in_any_core_window
           FROM posts p LEFT JOIN retrieval_hits h ON h.post_id=p.post_id
           LEFT JOIN jobs j ON j.job_key=h.job_key
           GROUP BY p.post_id ORDER BY p.published_at_utc,p.post_id"""
    ).fetchall()
    output_rows: list[dict[str, Any]] = []
    for row in rows:
        post_id = row["post_id"]
        prior = dict(old_rows.get(post_id, {}))
        current = {name: row[name] if name in row.keys() else "" for name in generated}
        current.update({name: prior.get(name, "") for name in fields if name not in generated})
        for variable in ("relevance_label", "notes"):
            current[variable] = annotation_values.get(post_id, {}).get(variable, prior.get(variable, ""))
            if prior.get(variable) and not annotation_values.get(post_id, {}).get(variable):
                now = utc_now()
                db.execute(
                    """INSERT INTO annotations
                       (post_id,study_id,coder_id,codebook_version,variable,value,coded_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(post_id,study_id,coder_id,codebook_version,variable)
                       DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",
                    (post_id, "unassigned", "legacy_csv", "unversioned", variable, prior[variable], now, now),
                )
        output_rows.append(current)
    db.commit()
    _atomic_csv(coding_path, fields, output_rows)
    _atomic_csv(export_dir / "master_posts.csv", fields, output_rows)

    table_exports = {
        "retrieval_hits.csv": "SELECT * FROM retrieval_hits ORDER BY hit_id",
        "post_relations.csv": "SELECT * FROM post_relations ORDER BY relation_id",
        "user_snapshots.csv": "SELECT * FROM user_snapshots ORDER BY snapshot_id",
        "metric_snapshots.csv": "SELECT * FROM metric_snapshots ORDER BY snapshot_id",
        "jobs.csv": "SELECT * FROM jobs ORDER BY created_at,job_key",
        "runs.csv": "SELECT * FROM runs ORDER BY started_at,run_id",
    }
    for filename, sql in table_exports.items():
        data = db.execute(sql).fetchall()
        columns = list(data[0].keys()) if data else [x[1] for x in db.execute(f"PRAGMA table_info({filename[:-4]})")]
        _atomic_csv(export_dir / filename, columns, (dict(row) for row in data))

    with (export_dir / "posts_parsed.jsonl").open("w", encoding="utf-8") as handle:
        for row in db.execute("SELECT post_id,raw_json,first_retrieved_at,last_retrieved_at FROM posts ORDER BY post_id"):
            handle.write(json_dumps({"post_id": row["post_id"], "first_retrieved_at": row["first_retrieved_at"],
                                     "last_retrieved_at": row["last_retrieved_at"], "tweet": json.loads(row["raw_json"])}) + "\n")
    with (export_dir / "raw_responses.jsonl").open("w", encoding="utf-8") as handle:
        for row in db.execute("SELECT * FROM raw_responses ORDER BY response_id"):
            handle.write(json_dumps(dict(row)) + "\n")
    return export_dir


def account_status(account_db: Path) -> list[dict[str, Any]]:
    if not account_db.exists():
        return []
    with sqlite3.connect(account_db) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT username,active,locks,stats,last_used,error_msg FROM accounts ORDER BY username")
        output = []
        for row in rows:
            item = dict(row)
            item["account_alias"] = "acct_" + sha256_text(item.pop("username"))[:8]
            output.append(item)
        return output


def collection_summary(db: sqlite3.Connection) -> dict[str, Any]:
    def scalar(sql: str) -> Any:
        return db.execute(sql).fetchone()[0]
    return {
        "schema_version": scalar("SELECT value FROM schema_meta WHERE key='schema_version'"),
        "quick_check": scalar("PRAGMA quick_check"),
        "posts": scalar("SELECT COUNT(*) FROM posts"),
        "raw_responses": scalar("SELECT COUNT(*) FROM raw_responses"),
        "retrieval_hits": scalar("SELECT COUNT(*) FROM retrieval_hits"),
        "relations": scalar("SELECT COUNT(*) FROM post_relations"),
        "user_snapshots": scalar("SELECT COUNT(*) FROM user_snapshots"),
        "metric_snapshots": scalar("SELECT COUNT(*) FROM metric_snapshots"),
        "jobs": [dict(x) for x in db.execute(
            "SELECT stage,kind,status,COUNT(*) AS n FROM jobs GROUP BY stage,kind,status ORDER BY stage,kind,status"
        )],
        "runs": [dict(x) for x in db.execute(
            "SELECT run_id,command,status,started_at,ended_at,jobs_started,jobs_finished,requests,wait_seconds FROM runs ORDER BY started_at DESC LIMIT 10"
        )],
    }


def write_audit_report(cfg: dict[str, Any], db: sqlite3.Connection) -> Path:
    out, _ = get_paths(cfg)
    audit_dir = out / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = audit_dir / f"collection_audit_{stamp}.md"
    queries, templates = load_query_registry(cfg)
    summary = collection_summary(db)
    accounts = account_status(resolve_from_config(cfg, cfg["account_db"]))
    status_lines = [
        f"| {x['stage']} | {x['kind']} | {x['status']} | {x['n']} |" for x in summary["jobs"]
    ]
    account_lines = [
        f"| {x['account_alias']} | {bool(x['active'])} | `{x['locks']}` | `{x['stats']}` | {x['last_used'] or ''} |"
        for x in accounts
    ]
    run_lines = [
        f"| {x['run_id']} | {x['status']} | {x['started_at']} | {x['ended_at'] or ''} | {x['jobs_started']} | {x['requests']} | {float(x['wait_seconds'] or 0):.1f} |"
        for x in summary["runs"]
    ]
    flagged = [dict(x) for x in db.execute(
        """SELECT label,start_date,end_date_exclusive,status,stop_reason,warning,error
           FROM jobs WHERE status NOT IN ('pending','complete','split_parent')
           ORDER BY updated_at DESC LIMIT 50"""
    )]
    flag_lines = [
        f"| {x['label']} | {x['start_date'] or ''} | {x['end_date_exclusive'] or ''} | {x['status']} | {x['stop_reason'] or ''} | {(x['warning'] or x['error'] or '').replace('|', '/')} |"
        for x in flagged
    ]
    report = f"""# WHO AI X collection audit

Generated: {utc_now()}  
Collector: {COLLECTOR_VERSION}  
twscrape: {twscrape_version()}  
Schema: {summary['schema_version']} (`PRAGMA quick_check={summary['quick_check']}`)  
Config SHA-256: `{config_sha(cfg)}`  
Query registry: `{cfg['query_registry']}` / `{cfg['query_version']}`

## Registry and scope

- Fixed query×window rows: {len(queries)} (P0={sum(q.stage == 'p0' for q in queries)}, P1={sum(q.stage == 'p1' for q in queries)}, P2={sum(q.stage == 'p2' for q in queries)}).
- Dynamic templates documented but disabled until verified values are supplied: {len(templates)}.
- Core windows are UTC half-open intervals and are checked again against parsed post timestamps.
- Search product defaults to Latest. Top creates separate job identities and is only for gap checks.

## Stored evidence

| Layer | Rows |
|---|---:|
| posts | {summary['posts']} |
| raw_responses | {summary['raw_responses']} |
| retrieval_hits | {summary['retrieval_hits']} |
| post_relations | {summary['relations']} |
| user_snapshots | {summary['user_snapshots']} |
| metric_snapshots | {summary['metric_snapshots']} |

## Job coverage

| Stage | Kind | Status | Jobs |
|---|---|---|---:|
{chr(10).join(status_lines) if status_lines else '| — | — | — | 0 |'}

## Recent runs

| Run | Status | Started UTC | Ended UTC | Jobs | Requests/attempts | Throttle wait seconds |
|---|---|---|---|---:|---:|---:|
{chr(10).join(run_lines) if run_lines else '| — | — | — | — | 0 | 0 | 0 |'}

## Flagged jobs

| Label | Start | End exclusive | Status | Stop reason | Note/error |
|---|---|---|---|---|---|
{chr(10).join(flag_lines) if flag_lines else '| — | — | — | — | — | — |'}

## Account pool (credential-free aliases)

| Alias | Active | Endpoint locks | Request counters | Last used |
|---|---|---|---|---|
{chr(10).join(account_lines) if account_lines else '| — | — | — | — | — |'}

## Rate and recovery controls

- Total concurrency defaults to {cfg['scheduler']['concurrency']} and is capped at {cfg['scheduler']['max_concurrency']}.
- Each account has one in-flight HTTP request globally; the minimum interval is {cfg['scheduler']['min_request_interval_seconds']} seconds and applies to internal pagination requests.
- Reliable endpoint headers trigger a reserve at {float(cfg['scheduler']['rate_limit_reserve_fraction']):.0%}; the endpoint waits for reset instead of consuming the reserve.
- Every response body is stored before parsing. Request headers, cookies, tokens, passwords, and account usernames are not stored in the research database or exports.
- Cursors are checkpointed after each yielded page. A non-null cursor at an unexpected end is partial/pagination-stalled, not complete.
- Legacy v1 rows retain their parsed twscrape objects, but no historical HTTP bodies existed to migrate; the raw-response layer begins with v2 requests.

## Known coverage limits

- These are posts still publicly accessible and searchable at collection time, not a complete historical archive.
- Search, reply, thread, `conversation_id:` and `url:` behavior can change and must be validated with known posts. Displayed reply/quote counts do not guarantee retrievability.
- Empty jobs remain `empty_unverified`; local caps, repeated/unresolved cursors, rate limits, authentication failures, and parse failures are distinct outcomes.
- Quoted or reposted objects embedded in a response are relations only until separately fetched as their own detail job.
- Interaction counts and user profiles are collection-time snapshots, not historical values from 2020/2022/2024.
"""
    path.write_text(report, encoding="utf-8")
    latest = audit_dir / "latest_collection_audit.md"
    latest.write_text(report, encoding="utf-8")
    return path
