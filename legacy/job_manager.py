import time
import threading
import json
import logging
import uuid
import traceback
from datetime import datetime, timedelta
import database
from concurrent.futures import ThreadPoolExecutor

# Configure Logging
logging.basicConfig(
    filename='background_jobs.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class JobManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(JobManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.worker_id = str(uuid.uuid4())[:8]
        self.is_running = False
        self.executor = ThreadPoolExecutor(max_workers=3) # Global concurrency limit
        self.polling_interval = 5  # Seconds
        logging.info(f"JobManager initialized. Worker ID: {self.worker_id}")

    def start_background_poller(self):
        """Starts the background thread that polls for pending jobs."""
        if self.is_running:
            logging.warning("JobManager poller is already running.")
            return

        self.is_running = True
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()
        logging.info("🚀 JobManager Poller Started.")

    def stop(self):
        self.is_running = False
        self.executor.shutdown(wait=False)
        logging.info("🛑 JobManager Stopped.")

    def submit_job(self, job_type: str, payload: dict) -> int:
        """
        Submits a new job to the database queue.
        Returns the Job ID.
        """
        conn = database.get_db_connection()
        c = conn.cursor()
        
        try:
            c.execute('''
                INSERT INTO background_jobs (type, payload, status, total_items, created_at)
                VALUES (?, ?, 'pending', ?, ?)
            ''', (job_type, json.dumps(payload), payload.get('count', 0), datetime.now()))
            
            job_id = c.lastrowid
            conn.commit()
            logging.info(f"📥 Job Submitted: ID {job_id} [{job_type}]")
            return job_id
        except Exception as e:
            logging.error(f"❌ Failed to submit job: {e}")
            return -1
        finally:
            conn.close()

    def _poll_loop(self):
        """Main loop that checks for pending jobs."""
        while self.is_running:
            try:
                # 1. Recover Stale Jobs (Processing > 10 mins with no update)
                self._recover_stale_jobs()
                
                # 2. Pick up a pending job
                job = self._claim_next_job()
                
                if job:
                    # Execute in thread pool
                    self.executor.submit(self._execute_job, job)
                else:
                    time.sleep(self.polling_interval)
                    
            except Exception as e:
                logging.error(f"Critical Poller Error: {e}")
                time.sleep(10)

    def _recover_stale_jobs(self):
        """Resets jobs that have been stuck in 'processing' for more than 10 minutes."""
        conn = database.get_db_connection()
        c = conn.cursor()
        try:
            # 15 minutes ago
            stale_threshold = datetime.now() - timedelta(minutes=15)
            
            c.execute('''
                UPDATE background_jobs 
                SET status = 'pending', worker_id = NULL, updated_at = ?
                WHERE status = 'processing' AND updated_at < ?
            ''', (datetime.now(), stale_threshold))
            
            if c.rowcount > 0:
                logging.info(f"🔄 Recovered {c.rowcount} stale jobs.")
                conn.commit()
        except Exception as e:
            logging.error(f"Error recovering stale jobs: {e}")
        finally:
            conn.close()

    def _claim_next_job(self):
        """
        Atomically claims a pending job.
        """
        conn = database.get_db_connection()
        conn.row_factory = database.sqlite3.Row
        c = conn.cursor()
        
        try:
            # Find oldest pending job
            c.execute("SELECT id FROM background_jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
            row = c.fetchone()
            
            if not row:
                return None
                
            job_id = row['id']
            
            # Atomic Update
            c.execute('''
                UPDATE background_jobs 
                SET status = 'processing', worker_id = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
            ''', (self.worker_id, datetime.now(), job_id))
            
            conn.commit()
            
            if c.rowcount == 1:
                # Fetch full details
                c.execute("SELECT * FROM background_jobs WHERE id = ?", (job_id,))
                return dict(c.fetchone())
            else:
                return None # Race condition, someone else grabbed it
                
        except Exception as e:
            logging.error(f"Error claiming job: {e}")
            return None
        finally:
            conn.close()

    def _execute_job(self, job):
        """
        Router for executing specific job types.
        """
        job_id = job['id']
        job_type = job['type']
        payload = json.loads(job['payload'])
        
        logging.info(f"⚙️ Processing Job {job_id}: {job_type}")
        
        try:
            if job_type == 'generation_batch':
                from background_jobs import process_generation_batch
                process_generation_batch(job_id, payload)
            else:
                raise ValueError(f"Unknown job type: {job_type}")
                
            # Completion is handled inside the processor usually, 
            # but we can enforce a final check here.
            
        except Exception as e:
            error_msg = str(e)
            traceback.print_exc()
            logging.error(f"❌ Job {job_id} Failed: {error_msg}")
            
            # Update DB to Failed
            conn = database.get_db_connection()
            c = conn.cursor()
            c.execute('''
                UPDATE background_jobs 
                SET status = 'failed', error_message = ?, completed_at = ? 
                WHERE id = ?
            ''', (error_msg, datetime.now(), job_id))
            conn.commit()
            conn.close()

    def get_job_status(self, job_id):
        """Returns the current status of a job."""
        conn = database.get_db_connection()
        conn.row_factory = database.sqlite3.Row
        c = conn.cursor()
        try:
            c.execute("SELECT * FROM background_jobs WHERE id = ?", (job_id,))
            row = c.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

# Singleton Accessor
def get_manager():
    return JobManager()
