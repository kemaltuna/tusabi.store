import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .database import get_db_connection
from .database import get_db_engine

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # -> medical_quiz_app
PAUSE_FLAG_PATH = PROJECT_ROOT / "generation_paused.flag"


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    type: str
    payload_raw: Any
    attempts: int
    max_attempts: int


class JobWorker:
    def __init__(
        self,
        *,
        worker_id: Optional[str] = None,
        poll_interval_s: float = 2.0,
        stale_after_minutes: int = 30,
    ) -> None:
        self.worker_id = worker_id or str(uuid.uuid4())[:8]
        self.poll_interval_s = max(0.2, float(poll_interval_s))
        self.stale_after = timedelta(minutes=max(1, int(stale_after_minutes)))
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_stale_recovery: float = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="job-worker", daemon=True)
        self._thread.start()
        logger.info("JobWorker started (worker_id=%s)", self.worker_id)

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=timeout_s)
        logger.info("JobWorker stopped (worker_id=%s)", self.worker_id)

    def _sleep(self) -> None:
        self._stop_event.wait(self.poll_interval_s)

    def _recover_stale_jobs(self) -> None:
        # Run at most once per minute to keep DB writes low.
        now = time.time()
        if now - self._last_stale_recovery < 60:
            return
        self._last_stale_recovery = now

        threshold = datetime.now() - self.stale_after
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute(
                """
                UPDATE background_jobs
                SET status = 'pending', worker_id = NULL, updated_at = ?
                WHERE status = 'processing' AND updated_at < ?
                """,
                (datetime.now(), threshold),
            )
            recovered = c.rowcount or 0
            conn.commit()
            if recovered:
                logger.warning("Recovered %s stale jobs (threshold=%s).", recovered, threshold)
        except Exception:
            logger.exception("Stale job recovery failed.")
        finally:
            conn.close()

    def _claim_next_job(self) -> Optional[ClaimedJob]:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            while True:
                engine = get_db_engine()
                if engine == "postgres":
                    # In Postgres we rely on row-level locking + SKIP LOCKED.
                    c.execute("BEGIN")
                    c.execute(
                        """
                        SELECT id, type, payload, attempts, max_attempts
                        FROM background_jobs
                        WHERE status = 'pending'
                        ORDER BY created_at ASC, id ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                        """
                    )
                else:
                    # SQLite: lock DB for write while selecting+updating.
                    c.execute("BEGIN IMMEDIATE")
                    c.execute(
                        """
                        SELECT id, type, payload, attempts, max_attempts
                        FROM background_jobs
                        WHERE status = 'pending'
                        ORDER BY created_at ASC, id ASC
                        LIMIT 1
                        """
                    )
                row = c.fetchone()
                if not row:
                    conn.commit()
                    return None

                job_id = int(row["id"])
                attempts = int(row["attempts"] or 0)
                max_attempts = int(row["max_attempts"] or 3)

                if attempts >= max_attempts:
                    msg = f"Max attempts exceeded ({attempts}/{max_attempts})."
                    c.execute(
                        """
                        UPDATE background_jobs
                        SET status = 'failed',
                            error_message = ?,
                            completed_at = ?,
                            updated_at = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (msg, datetime.now(), datetime.now(), job_id),
                    )
                    conn.commit()
                    logger.error("Job %s failed: %s", job_id, msg)
                    continue

                next_attempts = attempts + 1
                c.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'processing',
                        worker_id = ?,
                        attempts = ?,
                        updated_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (self.worker_id, next_attempts, datetime.now(), job_id),
                )
                if (c.rowcount or 0) != 1:
                    conn.commit()
                    return None

                conn.commit()
                return ClaimedJob(
                    id=job_id,
                    type=str(row["type"] or ""),
                    payload_raw=row["payload"],
                    attempts=next_attempts,
                    max_attempts=max_attempts,
                )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("Failed to claim next job.")
            return None
        finally:
            conn.close()

    def _mark_failed(self, job_id: int, message: str) -> None:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute(
                """
                UPDATE background_jobs
                SET status = 'failed',
                    error_message = ?,
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (message, datetime.now(), datetime.now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _execute_job(self, job: ClaimedJob) -> None:
        job_id = job.id
        if job.type != "generation_batch":
            self._mark_failed(job_id, f"Unknown job type: {job.type}")
            return

        payload = {}
        try:
            raw = job.payload_raw
            if isinstance(raw, (dict, list)):
                payload = raw
            elif raw:
                payload = json.loads(raw)
        except Exception as exc:
            self._mark_failed(job_id, f"Invalid payload JSON: {exc}")
            return

        try:
            from core.background_jobs import process_generation_batch_job

            process_generation_batch_job(job_id, payload)
        except Exception:
            # The job processor already updates DB status+error_message; keep worker alive.
            logger.exception("Job %s crashed during execution.", job_id)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if PAUSE_FLAG_PATH.exists():
                    logger.info("Generation paused (%s present).", PAUSE_FLAG_PATH.name)
                    self._sleep()
                    continue

                self._recover_stale_jobs()

                job = self._claim_next_job()
                if not job:
                    self._sleep()
                    continue

                logger.info("⚙️ Claimed Job %s (%s, attempt %s/%s).", job.id, job.type, job.attempts, job.max_attempts)
                self._execute_job(job)
            except Exception:
                logger.exception("Critical worker loop error; backing off.")
                self._stop_event.wait(5.0)


_worker_instance: Optional[JobWorker] = None


def start_job_worker() -> None:
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = JobWorker()
    _worker_instance.start()


def stop_job_worker() -> None:
    global _worker_instance
    if _worker_instance is None:
        return
    _worker_instance.stop()
