#!/usr/bin/env python3
"""Durable, single-worker execution of the fixed WHO X collection plan."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from who_x_core import (
    ROOT, backup_database, get_paths, load_config, open_db,
    register_jobs, resolve_from_config, utc_now,
)

PHASES = [
    ("p0", "search"), ("all", "context"), ("p1", "replies"),
    ("p1", "search"), ("p2", "search"), ("all", "context"),
]
KINDS = {"search": ("search",), "context": ("detail",), "replies": ("replies", "thread")}


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def scope(stage: str, mode: str) -> tuple[str, list[str]]:
    kinds = KINDS[mode]
    clause = f"stage IN ('p0','p1','p2') AND kind IN ({','.join('?' for _ in kinds)})"
    values = list(kinds)
    if stage != "all":
        clause += " AND stage=?"
        values.append(stage)
    return clause, values


def account_delay(account_path: Path, endpoint: str) -> float | None:
    """None means all sessions need user authentication; otherwise respect reset."""
    with sqlite3.connect(account_path) as db:
        rows = db.execute("SELECT locks FROM accounts WHERE active=1").fetchall()
    if not rows:
        return None
    delays = []
    for (locks_text,) in rows:
        value = json.loads(locks_text or "{}").get(endpoint)
        reset = datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() if value else 0
        delays.append(max(0.0, reset - time.time()))
    return min(delays)


def supervise(args: argparse.Namespace, status_path: Path) -> None:
    cfg = load_config(args.config)
    out, db_path = get_paths(cfg)
    account_path = resolve_from_config(cfg, cfg["account_db"])
    state = {"pid": os.getpid(), "started_at": utc_now(), "status": "starting", "phase": None}

    def save(**changes):
        state.update(changes, updated_at=utc_now())
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(status_path)

    save(status="waiting_existing_collector", waiting_pid=args.wait_pid)
    while process_exists(args.wait_pid):
        time.sleep(30)
        save(status="waiting_existing_collector")
    save(status="backing_up")
    state["backup"] = str(backup_database(db_path))
    db = open_db(db_path)
    register_jobs(db, cfg, stage="all", product="Latest")
    # A terminated process cannot still own its old run. Keep this distinct from completion.
    db.execute("UPDATE runs SET status='stopped:process_exited',ended_at=? WHERE status='running'", (utc_now(),))
    db.execute("UPDATE jobs SET status='pending',stop_reason='interrupted_previous_run',updated_at=? WHERE status='running' AND stage IN ('p0','p1','p2')", (utc_now(),))
    db.commit()
    child: subprocess.Popen | None = None
    retry_counts: dict[str, int] = {}

    def interrupted(signum, frame):
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=40)
            except subprocess.TimeoutExpired:
                child.terminate()
        save(status="stopped", reason="signal", signal=signum)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        for index, (stage, mode) in enumerate(PHASES):
            clause, values = scope(stage, mode)
            recovered = False
            transport_failures = 0
            save(status="running", phase=f"{index + 1}/{len(PHASES)} {stage}:{mode}")
            while True:
                # Retry interrupted/budgeted requests, but never endlessly replay stalled cursors.
                for row in db.execute(f"SELECT job_key,status,stop_reason FROM jobs WHERE {clause} AND status IN ('partial','rate_limited','auth_error') AND COALESCE(stop_reason,'') != 'pagination_stalled_or_unresolved_cursor'", values).fetchall():
                    budgeted = row['stop_reason'] in ('time_budget', 'hard_time_budget', 'interrupted_previous_run')
                    retry_key = row['job_key']
                    if row['status'] == 'partial' and not budgeted:
                        if retry_counts.get(retry_key, 0) >= 3:
                            continue
                        retry_counts[retry_key] = retry_counts.get(retry_key, 0) + 1
                    db.execute("UPDATE jobs SET status='pending',updated_at=? WHERE job_key=?", (utc_now(), retry_key))
                db.commit()
                pending = db.execute(f"SELECT COUNT(*) FROM jobs WHERE {clause} AND status='pending'", values).fetchone()[0]
                if not pending:
                    if recovered:
                        break
                    # One additional attempt for unresolved pagination in each phase.
                    db.execute(f"UPDATE jobs SET status='pending',updated_at=? WHERE {clause} AND status='partial' AND stop_reason='pagination_stalled_or_unresolved_cursor'", [utc_now(), *values])
                    db.commit()
                    recovered = True
                    if not db.execute(f"SELECT COUNT(*) FROM jobs WHERE {clause} AND status='pending'", values).fetchone()[0]:
                        break
                save(status="running", pending=pending)
                command = [sys.executable, str(ROOT / "who_x_collector.py"), "run", "--config", args.config,
                           "--stage", stage, "--mode", mode, "--concurrency", "1", "--max-minutes", "60"]
                child = subprocess.Popen(command, cwd=ROOT)
                code = child.wait()
                child = None
                run = db.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
                save(last_run_id=run["run_id"], last_run_status=run["status"])
                if code != 0:
                    save(status="paused_error", reason="collector_exit", exit_code=code)
                    return
                if run["status"] == "stopped:accounts_unavailable":
                    job = db.execute("SELECT * FROM jobs WHERE run_id=? ORDER BY updated_at DESC LIMIT 1", (run["run_id"],)).fetchone()
                    endpoint = job["endpoint"] or "SearchTimeline"
                    if job["stop_reason"] == "transport_error_accounts_cooling":
                        transport_failures += 1
                        if transport_failures >= 3:
                            save(status="paused_error", reason="repeated_transport_failure")
                            return
                    while True:
                        delay = account_delay(account_path, endpoint)
                        if delay is None:
                            save(status="waiting_authentication", endpoint=endpoint)
                            time.sleep(30)
                            continue
                        if delay > 0:
                            save(status="waiting_rate_reset", endpoint=endpoint, wait_seconds=round(delay, 1))
                            time.sleep(min(30, delay + 2))
                            continue
                        # Avoid a tight loop when account selection failed for another reason.
                        save(status="cooling_down", endpoint=endpoint)
                        time.sleep(30)
                        break
                else:
                    transport_failures = 0
            save(status="exporting")
            result = subprocess.run([sys.executable, str(ROOT / "who_x_collector.py"), "export", "--config", args.config], cwd=ROOT)
            if result.returncode:
                save(status="paused_error", reason="export_failed")
                return
        gaps = [dict(row) for row in db.execute("SELECT stage,kind,status,COUNT(*) AS n FROM jobs WHERE stage IN ('p0','p1','p2') AND status NOT IN ('complete','split_parent') GROUP BY stage,kind,status")]
        save(status="finished_with_gaps" if gaps else "finished", gaps=gaps,
             dynamic_templates="8 require verified values; no fabricated template values",
             ended_at=utc_now(), pending=0)
    except Exception as exc:
        # Do not persist exception text that could include credentials.
        save(status="paused_error", reason=type(exc).__name__)
        return
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "worker", "status"])
    parser.add_argument("--config", default=str(ROOT / "who_x_config.json"))
    parser.add_argument("--wait-pid", type=int, default=0)
    args = parser.parse_args()
    cfg = load_config(args.config)
    out, _ = get_paths(cfg)
    control = out / "full_run"
    control.mkdir(parents=True, exist_ok=True)
    status_path = control / "status.json"
    if args.action == "status":
        print(status_path.read_text() if status_path.exists() else '{"status":"not_started"}')
        return
    with (control / "supervisor.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("A full-plan supervisor is already running")
        if args.action == "worker":
            supervise(args, status_path)
            return
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        with (control / "collector.log").open("a", encoding="utf-8") as log:
            worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker", "--config", args.config,
                                       "--wait-pid", str(args.wait_pid)], cwd=ROOT,
                                      stdout=log, stderr=log, start_new_session=True)
        print(json.dumps({"pid": worker.pid, "status": "started", "log": str(control / "collector.log"),
                          "status_file": str(status_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
