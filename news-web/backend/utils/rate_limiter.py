"""
AI API 速率限制器 — 滑动窗口追踪 RPM / TPM，动态等待替代硬编码延迟。

限制参数：
  RPM: 100 次/分钟（60s 滑动窗口）
  TPM: 100,000 tokens/分钟（60s 滑动窗口）

Token 估算：
  英文约 4 chars/token，中文约 1.5-2 chars/token。
  保守取 3 chars/token 以覆盖混合语言场景。

用法：
  from utils.rate_limiter import ai_rate_limiter

  # 调用前等待（传估算 token 数）
  ai_rate_limiter.wait_if_needed(estimated_tokens=5000)
  result = api_call(...)

  # 调用后记录实际消耗（可选，从 API 响应中获取 usage）
  ai_rate_limiter.record(actual_tokens)
"""
import time
import threading
import logging
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 字符 → token 估算系数（保守值）
CHARS_PER_TOKEN = 3

# 滑动窗口时长（秒）
WINDOW_SECONDS = 60


@dataclass
class _Entry:
    timestamp: float
    tokens: int


class RateLimiter:
    """滑动窗口速率限制器，同时约束 RPM 和 TPM。"""

    def __init__(self, rpm: int = 100, tpm: int = 100_000):
        self.rpm_limit = rpm
        self.tpm_limit = tpm
        self._window: deque[_Entry] = deque()
        self._lock = threading.Lock()

    def _purge_expired(self, now: float) -> None:
        """移除窗口外的过期条目。调用方需持有 _lock。"""
        cutoff = now - WINDOW_SECONDS
        while self._window and self._window[0].timestamp < cutoff:
            self._window.popleft()

    def _current_rpm(self) -> int:
        """返回当前窗口内的请求数。调用方需持有 _lock。"""
        return len(self._window)

    def _current_tpm(self) -> int:
        """返回当前窗口内的 token 消耗。调用方需持有 _lock。"""
        return sum(e.tokens for e in self._window)

    def wait_if_needed(self, estimated_tokens: int = 0) -> None:
        """
        阻塞直到 RPM 和 TPM 约束同时满足。

        Args:
            estimated_tokens: 预估本次调用消耗的 token 数（0 表示不检查 TPM）
        """
        with self._lock:
            now = time.monotonic()
            self._purge_expired(now)

            # 逐轮回合直到两个约束都满足
            waited_rpm = 0.0
            waited_tpm = 0.0
            while True:
                now = time.monotonic()
                self._purge_expired(now)

                rpm_ok = self._current_rpm() < self.rpm_limit
                tpm_ok = (estimated_tokens <= 0 or
                          self._current_tpm() + estimated_tokens <= self.tpm_limit)

                if rpm_ok and tpm_ok:
                    break

                sleep_for = 0.0

                if not rpm_ok and self._window:
                    # 等到最早请求过期
                    oldest = self._window[0].timestamp
                    sleep_for = max(sleep_for, oldest + WINDOW_SECONDS - now + 0.1)
                    waited_rpm += sleep_for

                if not tpm_ok and self._window:
                    # 估算需要多少条目过期才能满足 TPM
                    needed = self._current_tpm() + estimated_tokens - self.tpm_limit
                    accumulated = 0
                    expire_at = now
                    for entry in self._window:
                        accumulated += entry.tokens
                        expire_at = entry.timestamp + WINDOW_SECONDS
                        if accumulated >= needed:
                            break
                    sleep_for = max(sleep_for, expire_at - now + 0.1)
                    waited_tpm += sleep_for

                # 释放锁等待，避免忙循环
                if sleep_for > 0:
                    self._lock.release()
                    try:
                        time.sleep(min(sleep_for, 5.0))  # 最长等 5 秒，避免极端情况死等
                    finally:
                        self._lock.acquire()

            if waited_rpm > 0:
                logger.debug(f"[RateLimiter] RPM 等待 {waited_rpm:.1f}s "
                             f"(当前 {self._current_rpm()}/{self.rpm_limit})")
            if waited_tpm > 0:
                logger.debug(f"[RateLimiter] TPM 等待 {waited_tpm:.1f}s "
                             f"(当前 {self._current_tpm()}/{self.tpm_limit})")

    def record(self, tokens: int = 0) -> None:
        """
        记录一次 API 调用及其 token 消耗。
        （可选 — 用于从 API 响应中获取真实 usage 后精确追踪）
        """
        if tokens < 0:
            tokens = 0
        with self._lock:
            now = time.monotonic()
            self._window.append(_Entry(timestamp=now, tokens=tokens))
            self._purge_expired(now)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """保守估算文本的 token 数。中文和英文混合场景取 3 chars/token。"""
        if not text:
            return 0
        return max(1, len(text) // CHARS_PER_TOKEN)

    def status(self) -> dict:
        """返回当前速率限制器状态（用于调试和监控）。"""
        with self._lock:
            self._purge_expired(time.monotonic())
            return {
                'rpm_current': self._current_rpm(),
                'rpm_limit': self.rpm_limit,
                'tpm_current': self._current_tpm(),
                'tpm_limit': self.tpm_limit,
                'window_entries': len(self._window),
            }


# 全局单例 — 所有 AI 调用共享此限制器
ai_rate_limiter = RateLimiter(rpm=100, tpm=100_000)
