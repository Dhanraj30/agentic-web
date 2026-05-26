"""
Cooldown Manager — exponential backoff for rate-limited LLM providers.
Inspired by OpenClaw's auth-profile rotation + cooldown system.
"""
from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

COOLDOWN_FILE = Path(__file__).parent.parent.parent / "data" / "cooldown_state.json"

BACKOFF_SECONDS = [60, 300, 1500, 3600]
MAX_BACKOFF = 3600
FAILURE_RESET_HOURS = 24


class CooldownManager:
    def __init__(self, state_path: Path = COOLDOWN_FILE):
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict = self._load()

    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.warning("Failed to load cooldown state: %s", e)
        return {"providers": {}, "last_prune": 0}

    def _save(self):
        try:
            self.state_path.write_text(json.dumps(self._state, indent=2))
        except Exception as e:
            logger.warning("Failed to save cooldown state: %s", e)

    def _prune_expired(self):
        now = time.time()
        last = self._state.get("last_prune", 0)
        if now - last < 300:
            return
        providers = self._state.get("providers", {})
        expired = [
            pid for pid, info in providers.items()
            if info.get("cooldown_until", 0) < now and (info.get("disabled_until", 0) or 0) < now
        ]
        for pid in expired:
            del providers[pid]
        self._state["last_prune"] = now
        if expired:
            self._save()

    def record_failure(self, provider_id: str, error_type: str = "rate_limit"):
        now = time.time()
        providers = self._state.setdefault("providers", {})
        info = providers.setdefault(provider_id, {"error_count": 0, "cooldown_until": 0, "last_error": None, "disabled_until": 0})

        if error_type == "billing":
            backoff = min(MAX_BACKOFF * 5, 14400)
            info["disabled_until"] = now + backoff
            info["disabled_reason"] = "billing"
            logger.info("Provider %s disabled for %ss (billing)", provider_id, backoff)
        else:
            info["error_count"] = info.get("error_count", 0) + 1
            ec = info["error_count"]
            backoff = BACKOFF_SECONDS[min(ec - 1, len(BACKOFF_SECONDS) - 1)] if ec > 0 else 60
            info["cooldown_until"] = now + backoff
            info["last_error"] = error_type
            info.pop("disabled_until", None)
            logger.info("Provider %s on cooldown for %ss (attempt %d, %s)", provider_id, backoff, ec, error_type)

        self._save()

    def record_success(self, provider_id: str):
        providers = self._state.setdefault("providers", {})
        if provider_id in providers:
            del providers[provider_id]
            self._save()

    def is_available(self, provider_id: str) -> bool:
        self._prune_expired()
        providers = self._state.get("providers", {})
        info = providers.get(provider_id)
        if not info:
            return True
        now = time.time()
        disabled = info.get("disabled_until", 0)
        if disabled and disabled > now:
            return False
        cooldown = info.get("cooldown_until", 0)
        if cooldown > now:
            return False
        return True

    def get_cooldown_remaining(self, provider_id: str) -> int:
        providers = self._state.get("providers", {})
        info = providers.get(provider_id)
        if not info:
            return 0
        now = time.time()
        until = max(info.get("cooldown_until", 0), info.get("disabled_until", 0))
        return max(0, int(until - now))

    def available(self, provider_ids: list[str]) -> list[str]:
        return [p for p in provider_ids if self.is_available(p)]

    def get_status(self) -> dict:
        self._prune_expired()
        result = {}
        for pid, info in self._state.get("providers", {}).items():
            remaining = self.get_cooldown_remaining(pid)
            if remaining > 0:
                result[pid] = {
                    "remaining_seconds": remaining,
                    "error_count": info.get("error_count", 0),
                    "last_error": info.get("last_error"),
                    "disabled": "disabled_until" in info,
                }
        return result
