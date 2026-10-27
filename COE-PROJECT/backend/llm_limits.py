"""
llm_limits.py — shared Groq rate-limit guard.

Groq enforces a tokens-per-minute (TPM) quota per organisation (8,000 on the free
tier). Concurrent callers (ward batch evaluation, the live simulator, the benchmark)
would otherwise burst through it and get 429s, which the pipeline reports as failed
evaluations. This keeps all LLM calls in the process inside a rolling 60-second token
budget. Raise GROQ_TPM_LIMIT on a paid tier.
"""
import os
import re
import threading
import time

TPM_LIMIT = int(os.environ.get("GROQ_TPM_LIMIT", "8000"))
# Leave headroom: other processes (or a restart) may be sharing the same org quota
BUDGET_FRACTION = float(os.environ.get("GROQ_TPM_UTILISATION", "0.8"))
# Used to reserve budget before the real usage is known
ESTIMATED_TOKENS_PER_CALL = int(os.environ.get("GROQ_EST_TOKENS_PER_CALL", "1500"))
WINDOW_SECONDS = 60.0


class TokenBudget:
    """Rolling 60-second token budget shared by all LLM callers; reservations are replaced by real usage after each call."""
    def __init__(self, tpm: int, fraction: float):
        """Limit = tpm * fraction (headroom for other users of the same quota)."""
        self.limit = max(1, int(tpm * fraction))
        self._entries: list[list] = []  # [timestamp, tokens]
        self._lock = threading.Lock()

    def _purge(self, now: float):
        """Drop reservations older than the window."""
        self._entries = [e for e in self._entries if now - e[0] < WINDOW_SECONDS]

    def acquire(self, tokens: int = ESTIMATED_TOKENS_PER_CALL) -> list:
        """Block until `tokens` fit in the rolling window; returns a handle for settle()."""
        tokens = min(tokens, self.limit)
        while True:
            with self._lock:
                now = time.monotonic()
                self._purge(now)
                used = sum(e[1] for e in self._entries)
                if used + tokens <= self.limit or not self._entries:
                    entry = [now, tokens]
                    self._entries.append(entry)
                    return entry
                wait = WINDOW_SECONDS - (now - self._entries[0][0])
            time.sleep(min(max(wait, 0.2), 5.0))

    def settle(self, entry: list, actual_tokens: int):
        """Replace the reservation with what the call really used."""
        with self._lock:
            entry[1] = max(0, int(actual_tokens))

    def penalise(self, seconds: float):
        """After a 429, block the whole window for roughly `seconds`."""
        with self._lock:
            now = time.monotonic()
            # A phantom entry that fills the budget until the server's cool-down passes
            self._entries.append([now - WINDOW_SECONDS + seconds, self.limit])


budget = TokenBudget(TPM_LIMIT, BUDGET_FRACTION)

_RETRY_AFTER = re.compile(r"try again in (?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", re.IGNORECASE)


def retry_after_seconds(error: Exception) -> float | None:
    """Parse Groq's 'Please try again in 10.38s' hint from a 429 error, else None."""
    text = str(error)
    if "429" not in text and "rate_limit" not in text:
        return None
    m = _RETRY_AFTER.search(text)
    if not m or not (m.group(1) or m.group(2)):
        return 5.0
    return int(m.group(1) or 0) * 60 + float(m.group(2) or 0)
