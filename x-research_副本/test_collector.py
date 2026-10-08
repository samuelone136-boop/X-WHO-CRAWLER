import csv
import asyncio
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from who_x_core import (
    export_data,
    job_key,
    load_config,
    load_query_registry,
    make_job,
    open_db,
    record_post,
    register_jobs,
    segments,
    update_job,
)
from who_x_runtime import install_httpx_timeout_patch, prepare_jobs_for_run
from who_x_full_run import account_delay


class Model(SimpleNamespace):
    def dict(self):
        def convert(value):
            if isinstance(value, Model):
                return {key: convert(item) for key, item in vars(value).items()}
            if isinstance(value, list):
                return [convert(item) for item in value]
            return value
        return convert(self)


class MockTweet(Model):
    def __init__(
        self,
        post_id,
        published,
        *,
        likes=3,
        view_count=None,
        reply_to=None,
        conversation=None,
        quoted=None,
        reposted=None,
    ):
        user = Model(
            id=123,
            username="sample",
            displayname="Sample User",
            rawDescription="profile",
            location=None,
            followersCount=10,
            friendsCount=5,
            statusesCount=20,
            verified=None,
            protected=False,
        )
        super().__init__(
            id=post_id,
            date=published,
            user=user,
            rawContent="sample text",
            lang="en",
            likeCount=likes,
            retweetCount=4,
            replyCount=1,
            quoteCount=2,
            viewCount=view_count,
            bookmarkedCount=None,
            conversationId=conversation or post_id,
            inReplyToTweetId=reply_to,
            quotedTweet=quoted,
            retweetedTweet=reposted,
            hashtags=["WHO"],
            cashtags=[],
            mentionedUsers=[],
            links=[Model(url="https://example.org", text="example.org", tcourl="https://t.co/x")],
            media=Model(photos=[], videos=[], animated=[]),
            url=f"https://x.com/sample/status/{post_id}",
        )


def add_raw_response(db, job):
    return db.execute(
        """INSERT INTO raw_responses
           (job_key,endpoint,request_method,request_json,requested_at,response_body)
           VALUES(?,?,?,?,?,?)""",
        (job, "SearchTimeline", "GET", "{}", "2026-10-08T00:00:00+00:00", "{}"),
    ).lastrowid


class CollectorTests(unittest.TestCase):
    def test_all_resume_excludes_legacy_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            db = open_db(Path(folder) / "test.sqlite")
            old = make_job(db, "search", "old", "hello", date(2024, 4, 2), date(2024, 4, 9))
            new = make_job(db, "search", "new", "hello", date(2024, 4, 2), date(2024, 4, 9))
            db.execute("UPDATE jobs SET stage='legacy',status='empty' WHERE job_key=?", (old,))
            db.execute("UPDATE jobs SET stage='p0',status='partial' WHERE job_key=?", (new,))
            db.commit()
            prepare_jobs_for_run(db, command="resume", stage="all", mode="all", retry_empty=True)
            self.assertEqual(db.execute("SELECT status FROM jobs WHERE job_key=?", (old,)).fetchone()[0], "empty")
            self.assertEqual(db.execute("SELECT status FROM jobs WHERE job_key=?", (new,)).fetchone()[0], "pending")
            db.close()

    def test_account_wait_honors_endpoint_reset_and_inactive_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "accounts.sqlite"
            reset = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE accounts(active INTEGER,locks TEXT)")
                db.execute("INSERT INTO accounts VALUES(0,'{}')")
                db.execute("INSERT INTO accounts VALUES(1,?)", (json.dumps({"SearchTimeline": reset}),))
            self.assertGreater(account_delay(path, "SearchTimeline"), 590)
            self.assertEqual(account_delay(path, "TweetDetail"), 0)
            with sqlite3.connect(path) as db:
                db.execute("UPDATE accounts SET active=0")
            self.assertIsNone(account_delay(path, "SearchTimeline"))

    def test_twscrape_http_timeout_is_process_local_and_restored(self):
        from twscrape.http import HttpxClient

        original = HttpxClient.__init__
        restore = install_httpx_timeout_patch(30)
        try:
            client = HttpxClient(headers={"user-agent": "test"})
            self.assertEqual(client._client.timeout.connect, 30)
            self.assertEqual(client._client._transport._pool._retries, 0)
            asyncio.run(client.aclose())
        finally:
            restore()
        self.assertIs(HttpxClient.__init__, original)

    def test_segments_are_half_open(self):
        actual = list(segments(date(2024, 4, 2), date(2024, 4, 17), 7))
        self.assertEqual(
            actual,
            [
                (date(2024, 4, 2), date(2024, 4, 9)),
                (date(2024, 4, 9), date(2024, 4, 16)),
                (date(2024, 4, 16), date(2024, 4, 17)),
            ],
        )

    def test_query_registry_matches_documented_counts(self):
        cfg = load_config(Path(__file__).parent / "who_x_config.json")
        queries, templates = load_query_registry(cfg)
        self.assertEqual(len(queries), 103)
        self.assertEqual(len(templates), 8)
        self.assertEqual(sum(item.stage == "p0" for item in queries), 51)
        self.assertFalse(any("since:" in item.text for item in queries))

    def test_job_key_changes_when_query_changes(self):
        common = dict(
            kind="search",
            label="S24-01",
            start=date(2024, 4, 2),
            end=date(2024, 4, 9),
            query_version="v1",
            product="Latest",
        )
        first = job_key(query_text="SARAH WHO", **common)
        second = job_key(query_text='"S.A.R.A.H." WHO', **common)
        self.assertNotEqual(first, second)
        self.assertEqual(first, job_key(query_text="SARAH WHO", **common))

    def test_registers_full_sliced_plan_without_duplicate_jobs(self):
        cfg = load_config(Path(__file__).parent / "who_x_config.json")
        with tempfile.TemporaryDirectory() as folder:
            db = open_db(Path(folder) / "test.sqlite")
            counts = register_jobs(db, cfg, stage="all", product="Latest")
            self.assertEqual(counts["search"], 751)
            self.assertEqual(counts["seed"], 9)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 760)
            register_jobs(db, cfg, stage="all", product="Latest")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 760)
            register_jobs(db, cfg, stage="p0", product="Top")
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM jobs WHERE product='Top'").fetchone()[0], 335
            )
            db.close()

    def test_date_filter_dedup_keeps_multiple_discovery_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            db = open_db(Path(folder) / "test.sqlite")
            first = make_job(db, "search", "A", "hello", date(2024, 4, 2), date(2024, 4, 9))
            second = make_job(db, "search", "B", "hello again", date(2024, 4, 2), date(2024, 4, 9))
            tweet = MockTweet(10, datetime(2024, 4, 2, tzinfo=timezone.utc))
            self.assertTrue(record_post(db, tweet, first, date(2024, 4, 2), date(2024, 4, 9)))
            self.assertTrue(record_post(db, tweet, second, date(2024, 4, 2), date(2024, 4, 9)))
            outside = MockTweet(11, datetime(2024, 4, 9, tzinfo=timezone.utc))
            self.assertFalse(record_post(db, outside, first, date(2024, 4, 2), date(2024, 4, 9)))
            db.commit()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 2)
            self.assertEqual(
                db.execute("SELECT COUNT(DISTINCT job_key) FROM retrieval_hits WHERE post_id='10'").fetchone()[0],
                2,
            )
            db.close()

    def test_snapshots_append_and_nulls_stay_null(self):
        with tempfile.TemporaryDirectory() as folder:
            db = open_db(Path(folder) / "test.sqlite")
            key = make_job(db, "search", "A", "hello", date(2024, 4, 2), date(2024, 4, 9))
            first_response = add_raw_response(db, key)
            second_response = add_raw_response(db, key)
            record_post(
                db,
                MockTweet(10, datetime(2024, 4, 2, tzinfo=timezone.utc), likes=3, view_count=None),
                key,
                date(2024, 4, 2),
                date(2024, 4, 9),
                response_id=first_response,
            )
            record_post(
                db,
                MockTweet(10, datetime(2024, 4, 2, tzinfo=timezone.utc), likes=9, view_count=100),
                key,
                date(2024, 4, 2),
                date(2024, 4, 9),
                response_id=second_response,
            )
            db.commit()
            snapshots = db.execute(
                "SELECT like_count,view_count FROM metric_snapshots WHERE post_id='10' ORDER BY snapshot_id"
            ).fetchall()
            self.assertEqual([(row[0], row[1]) for row in snapshots], [(3, None), (9, 100)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM user_snapshots").fetchone()[0], 2)
            db.close()
            reopened = open_db(Path(folder) / "test.sqlite")
            self.assertEqual(reopened.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0], 2)
            self.assertEqual(reopened.execute("SELECT COUNT(*) FROM user_snapshots").fetchone()[0], 2)
            self.assertEqual(reopened.execute("SELECT COUNT(*) FROM retrieval_hits").fetchone()[0], 2)
            reopened.close()

    def test_embedded_quote_is_relation_not_fabricated_standalone_post(self):
        with tempfile.TemporaryDirectory() as folder:
            db = open_db(Path(folder) / "test.sqlite")
            key = make_job(db, "search", "A", "hello", date(2024, 4, 2), date(2024, 4, 9))
            quoted = MockTweet(99, datetime(2024, 4, 1, tzinfo=timezone.utc))
            tweet = MockTweet(10, datetime(2024, 4, 2, tzinfo=timezone.utc), quoted=quoted)
            record_post(db, tweet, key, date(2024, 4, 2), date(2024, 4, 9))
            db.commit()
            self.assertIsNone(db.execute("SELECT 1 FROM posts WHERE post_id='99'").fetchone())
            relation = db.execute(
                "SELECT relation_type FROM post_relations WHERE from_post_id='10' AND to_post_id='99'"
            ).fetchone()
            self.assertEqual(relation[0], "quotes")
            db.close()

    def test_export_preserves_manual_and_custom_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cfg = {
                "_config_path": str(root / "config.json"),
                "output_dir": "out",
            }
            db = open_db(root / "test.sqlite")
            key = make_job(db, "search", "A", "hello", date(2024, 4, 2), date(2024, 4, 9))
            record_post(
                db,
                MockTweet(10, datetime(2024, 4, 2, tzinfo=timezone.utc)),
                key,
                date(2024, 4, 2),
                date(2024, 4, 9),
            )
            db.commit()
            coding = root / "out" / "coding" / "master_posts.csv"
            coding.parent.mkdir(parents=True)
            with coding.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["post_id", "relevance_label", "notes", "custom_manual_field"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "post_id": "10",
                        "relevance_label": "include",
                        "notes": "checked by coder",
                        "custom_manual_field": "keep-me",
                    }
                )
            export_data(cfg, db)
            export_data(cfg, db)
            with coding.open(newline="", encoding="utf-8-sig") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["relevance_label"], "include")
            self.assertEqual(row["notes"], "checked by coder")
            self.assertEqual(row["custom_manual_field"], "keep-me")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM annotations").fetchone()[0], 2)
            db.close()

    def test_legacy_migration_is_additive_and_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite"
            with sqlite3.connect(path) as db:
                db.executescript(
                    """
                    CREATE TABLE posts (
                      post_id TEXT PRIMARY KEY,published_at_utc TEXT,username TEXT,author_id TEXT,
                      text TEXT,lang TEXT,like_count INTEGER,repost_count INTEGER,reply_count INTEGER,
                      quote_count INTEGER,view_count INTEGER,conversation_id TEXT,reply_to_id TEXT,
                      quoted_id TEXT,raw_json TEXT NOT NULL,first_retrieved_at TEXT NOT NULL,
                      last_retrieved_at TEXT NOT NULL);
                    CREATE TABLE jobs (
                      job_key TEXT PRIMARY KEY,kind TEXT NOT NULL,label TEXT NOT NULL,query TEXT,
                      start_date TEXT,end_date_exclusive TEXT,status TEXT NOT NULL,raw_count INTEGER DEFAULT 0,
                      unique_count INTEGER DEFAULT 0,valid_count INTEGER DEFAULT 0,warning TEXT,error TEXT,
                      updated_at TEXT NOT NULL);
                    CREATE TABLE hits (
                      post_id TEXT NOT NULL,job_key TEXT NOT NULL,in_window INTEGER NOT NULL,found_at TEXT NOT NULL,
                      PRIMARY KEY(post_id,job_key));
                    """
                )
                db.execute(
                    "INSERT INTO posts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "1", "2024-04-02T00:00:00+00:00", "u", "2", "t", "en", 1, 2, 3, 4,
                        None, "1", None, None, "{}", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
                    ),
                )
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "old", "search", "old", "q", "2024-04-02", "2024-04-03", "complete",
                        1, 1, 1, None, None, "2026-01-01T00:00:00+00:00",
                    ),
                )
                db.execute("INSERT INTO hits VALUES('1','old',1,'2026-01-01T00:00:00+00:00')")
            first = open_db(path)
            self.assertEqual(first.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 1)
            self.assertEqual(first.execute("SELECT COUNT(*) FROM retrieval_hits").fetchone()[0], 1)
            self.assertEqual(first.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0], 1)
            first.close()
            second = open_db(path)
            self.assertEqual(second.execute("SELECT COUNT(*) FROM retrieval_hits").fetchone()[0], 1)
            self.assertEqual(second.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0], 1)
            self.assertEqual(second.execute("PRAGMA quick_check").fetchone()[0], "ok")
            second.close()

    def test_job_status_update_keeps_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            db = open_db(Path(folder) / "test.sqlite")
            key = make_job(db, "search", "A", "hello", date(2024, 4, 2), date(2024, 4, 9))
            update_job(db, key, "partial", 3, 2, 1, stop_reason="time_budget", cursor="cursor-1")
            row = db.execute("SELECT * FROM jobs WHERE job_key=?", (key,)).fetchone()
            self.assertEqual((row["raw_count"], row["unique_count"], row["valid_count"]), (3, 2, 1))
            self.assertEqual(row["cursor"], "cursor-1")
            self.assertEqual(row["stop_reason"], "time_budget")
            db.close()


if __name__ == "__main__":
    unittest.main()
