#!/usr/bin/env python3
"""WHO AI X collector v2.

Collects only publicly accessible material through an already-authorized twscrape
account database. It does not solve challenges, rotate proxies, reset rate limits,
or bypass access controls.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from who_x_core import (
    COLLECTOR_VERSION,
    ROOT,
    account_status,
    backup_database,
    collection_summary,
    export_data,
    get_paths,
    job_key,
    load_config,
    load_query_registry,
    make_job,
    open_db,
    post_date,
    record_post,
    register_jobs,
    resolve_from_config,
    segments,
    twscrape_version,
    update_job,
    write_audit_report,
)
from who_x_runtime import run_collection


def needs_migration_backup(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        with sqlite3.connect(db_path) as db:
            table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
            ).fetchone()
            if not table:
                return True
            row = db.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            return not row or int(row[0]) < 2
    except sqlite3.DatabaseError:
        return True


def ensure_migration_backup(db_path: Path) -> Path | None:
    if not needs_migration_backup(db_path):
        return None
    return backup_database(db_path)


def plan(cfg: dict[str, Any], stage: str) -> None:
    queries, templates = load_query_registry(cfg)
    allowed = {"p0", "p1", "p2"} if stage == "all" else {stage}
    selected = [query for query in queries if query.stage in allowed]
    query_counts = Counter(query.stage for query in selected)
    job_counts: Counter[str] = Counter()
    for query in selected:
        window = cfg["windows"][query.window_id]
        pieces = list(
            segments(
                date.fromisoformat(window["start_date"]),
                date.fromisoformat(window["end_date_exclusive"]),
                int(cfg["window_days"]),
            )
        )
        job_counts[query.stage] += len(pieces)
    seed_jobs = sum(
        len(seed.get("modes", ["details", "replies", "thread"]))
        for seed in cfg.get("seed_posts", [])
        if seed.get("stage", "p1") in allowed
    )
    print(f"Collector {COLLECTOR_VERSION}; twscrape {twscrape_version()}")
    print(f"Registry: {cfg['query_registry']} ({cfg['query_version']})")
    print(
        f"Fixed query×window rows: {len(queries)}; selected: {len(selected)} "
        f"({', '.join(f'{k}={query_counts[k]}' for k in ('p0','p1','p2') if query_counts[k])})"
    )
    print(
        f"Initial 7-day search jobs: {sum(job_counts.values())} "
        f"({', '.join(f'{k}={job_counts[k]}' for k in ('p0','p1','p2') if job_counts[k])})"
    )
    print(f"Seed context/reply jobs: {seed_jobs}")
    print(f"Dynamic templates documented but not runnable until filled: {len(templates)}")
    print("Search product: Latest by default; Top must be run separately and has distinct job keys.")


def report(db: sqlite3.Connection, cfg: dict[str, Any] | None = None) -> None:
    summary = collection_summary(db)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if cfg:
        accounts = account_status(resolve_from_config(cfg, cfg["account_db"]))
        print(json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WHO AI X research collector v2")
    parser.add_argument(
        "command",
        choices=["plan", "init", "run", "resume", "status", "report", "export", "audit", "backup"],
    )
    parser.add_argument("--config", default=str(ROOT / "who_x_config.json"))
    parser.add_argument("--stage", choices=["p0", "p1", "p2", "all"], default="p0")
    parser.add_argument("--mode", choices=["search", "replies", "context", "all"], default="search")
    parser.add_argument("--product", choices=["Latest", "Top"], default="Latest")
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--max-jobs", type=int, default=0, help="0 means no job-count cap")
    parser.add_argument("--max-minutes", type=float, default=0, help="0 means no run time cap")
    parser.add_argument("--retry-empty", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cfg = load_config(args.config)
    if args.command == "plan":
        plan(cfg, args.stage)
        return
    out, db_path = get_paths(cfg)
    collection_lock = None
    if args.command in {"run", "resume"}:
        out.mkdir(parents=True, exist_ok=True)
        collection_lock = (out / "collector.lock").open("a+")
        try:
            fcntl.flock(collection_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            collection_lock.close()
            raise SystemExit("Another collector is already running for this output directory")
    if args.command == "backup":
        if not db_path.exists():
            raise SystemExit(f"database does not exist: {db_path}")
        print(backup_database(db_path))
        return
    backup = ensure_migration_backup(db_path)
    if backup:
        print(f"Pre-migration SQLite backup: {backup}")
    db = open_db(db_path)
    try:
        if args.command == "init":
            counts = register_jobs(db, cfg, stage=args.stage, product=args.product)
            print(json.dumps({"database": str(db_path), "registered": counts}, ensure_ascii=False, indent=2))
            return
        if args.command in {"status", "report"}:
            report(db, cfg)
            return
        if args.command == "audit":
            path = write_audit_report(cfg, db)
            print(path)
            return
        if args.command == "export":
            export_dir = export_data(cfg, db)
            audit_path = write_audit_report(cfg, db)
            print(json.dumps({"export_dir": str(export_dir), "coding_csv": str(out / 'coding' / 'master_posts.csv'),
                              "audit_report": str(audit_path)}, ensure_ascii=False, indent=2))
            return
        if args.command in {"run", "resume"}:
            registered = register_jobs(db, cfg, stage=args.stage, product=args.product)
            concurrency = args.concurrency or int(cfg["scheduler"]["concurrency"])
            run_id, status = asyncio.run(
                run_collection(
                    cfg, db, command=args.command, mode=args.mode, stage=args.stage,
                    product=args.product, concurrency=concurrency, max_jobs=args.max_jobs,
                    max_minutes=args.max_minutes, retry_empty=args.retry_empty,
                )
            )
            audit_path = write_audit_report(cfg, db)
            print(json.dumps({"run_id": run_id, "status": status, "registered": registered,
                              "audit_report": str(audit_path)}, ensure_ascii=False, indent=2))
            return
    finally:
        db.close()
        if collection_lock is not None:
            collection_lock.close()


if __name__ == "__main__":
    main()
