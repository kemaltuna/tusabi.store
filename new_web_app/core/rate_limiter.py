
import random
import time
import logging

class RateLimiter:
    """
    Global helper to manage rate limits and circuit breaking across threads.
    Shared state is managed via class variables.
    """
    _last_request_time = 0
    _request_interval = 0.5  # Max 2 req/sec baseline (DeepSeek is fast? Verify limits)
                             # DeepSeek has generous limits usually, but let's be safe.
    _cooldown_until = 0.0

    @classmethod
    def wait_for_slot(cls):
        # 1. Global Circuit Breaker Check
        current = time.time()
        if current < cls._cooldown_until:
            wait_time = cls._cooldown_until - current
            logging.warning(f"🛑 DeepSeek Global Circuit Breaker Active. Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)
            current = time.time()
        
        # 2. RPM / Interval Jitter
        elapsed = current - cls._last_request_time
        if elapsed < cls._request_interval:
            sleep_time = cls._request_interval - elapsed
            time.sleep(sleep_time)
        
        cls._last_request_time = time.time()

    @classmethod
    def trigger_circuit_breaker(cls, duration=60):
        logging.error(f"⚠️ Triggering Circuit Breaker for {duration} seconds (429/Overload).")
        cls._cooldown_until = time.time() + duration

