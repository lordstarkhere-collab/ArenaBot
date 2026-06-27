import os
import time
import collections
import requests
import logging

logger = logging.getLogger("arenabot")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


class GroqKeyRotator:
    def __init__(self):
        self.keys = [v for k, v in sorted(os.environ.items()) if k.startswith("GROQ_API_KEY_") and v]
        if not self.keys:
            raise EnvironmentError("FATAL: No GROQ_API_KEY_* environment variables found.")
        self.current_index = 0
        self.cooldown_until = [0.0] * len(self.keys)

        # Aggregated usage stats
        self.total_requests = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.rate_limit_hits = 0
        self.started_at = time.time()

        # Per-source token tracking
        self.source_tokens: dict[str, int] = {
            "arena-bot": 0,
            "mention": 0,
            "training": 0,
        }
        self.source_requests: dict[str, int] = {
            "arena-bot": 0,
            "mention": 0,
            "training": 0,
        }

        # Ring buffer — last 5 requests
        self.recent_log: collections.deque = collections.deque(maxlen=5)

        logger.info("✅ AI engine initialized")

    @property
    def current_key(self) -> str:
        return self.keys[self.current_index]

    def _rotate(self):
        n = len(self.keys)
        for _ in range(n):
            self.current_index = (self.current_index + 1) % n
            if time.time() > self.cooldown_until[self.current_index]:
                logger.debug(f"AI engine rotated to slot {self.current_index + 1}")
                return
        # All cooling — wait for the soonest one
        wait = max(0, min(self.cooldown_until) - time.time())
        logger.warning(f"AI engine cooling down. Waiting {wait:.0f}s...")
        time.sleep(wait + 0.5)
        self.current_index = self.cooldown_until.index(min(self.cooldown_until))
        logger.info("AI engine recovered")

    def _mark_rate_limited(self):
        self.rate_limit_hits += 1
        self.cooldown_until[self.current_index] = time.time() + 62
        logger.warning("AI engine slot cooling, rotating...")
        self._rotate()

    @property
    def status(self) -> dict:
        now = time.time()
        cooling = sum(1 for t in self.cooldown_until if t > now)
        available = len(self.keys) - cooling
        if available == len(self.keys):
            health = "Healthy"
        elif available > 0:
            health = "Reduced capacity"
        else:
            wait = max(0, min(self.cooldown_until) - now)
            health = f"Cooling ({wait:.0f}s)"

        uptime_s = int(now - self.started_at)
        h, m, s = uptime_s // 3600, (uptime_s % 3600) // 60, uptime_s % 60

        return {
            "health": health,
            "total_requests": self.total_requests,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "uptime": f"{h}h {m}m {s}s",
            "rate_limit_hits": self.rate_limit_hits,
            "source_tokens": dict(self.source_tokens),
            "source_requests": dict(self.source_requests),
            "recent_log": list(self.recent_log),
        }

    def chat(self, messages: list[dict], max_tokens: int = 1500, source: str = "arena-bot") -> str:
        """Blocking HTTP call — must be run via asyncio.to_thread() from async code."""
        attempts = len(self.keys) * 2 + 2
        for attempt in range(attempts):
            try:
                resp = requests.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {self.current_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_MODEL,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.4,
                    },
                    timeout=30,
                )
                if resp.status_code == 429:
                    self._mark_rate_limited()
                    continue
                if resp.status_code >= 500:
                    logger.warning(f"AI server error {resp.status_code}, retrying...")
                    time.sleep(2)
                    continue
                resp.raise_for_status()
                data = resp.json()

                usage = data.get("usage", {})
                p_tokens = usage.get("prompt_tokens", 0)
                c_tokens = usage.get("completion_tokens", 0)
                total = p_tokens + c_tokens

                # Aggregate stats
                self.total_requests += 1
                self.total_prompt_tokens += p_tokens
                self.total_completion_tokens += c_tokens

                # Per-source stats
                src = source if source in self.source_tokens else "arena-bot"
                self.source_tokens[src] += total
                self.source_requests[src] += 1

                # Find the user question for the log preview
                user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
                preview = (user_msg[:45] + "…") if len(user_msg) > 45 else user_msg

                self.recent_log.append({
                    "source": src,
                    "preview": preview,
                    "prompt_tokens": p_tokens,
                    "completion_tokens": c_tokens,
                    "total_tokens": total,
                    "timestamp": time.time(),
                })

                return data["choices"][0]["message"]["content"]

            except requests.Timeout:
                logger.warning("AI request timed out, retrying...")
                time.sleep(2)
                continue
            except Exception as e:
                logger.error(f"AI engine error: {e}")
                raise

        raise RuntimeError("AI engine temporarily unavailable. Please try again in a moment.")


groq = GroqKeyRotator()
