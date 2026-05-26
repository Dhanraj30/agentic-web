"""
LLM Router — AgenticWeb
Supports: Gemini, Groq, DeepSeek, Claude, OpenAI, OpenRouter
Two modes:
  LLMRouter.complete()   — direct SDK calls (simple use)
  build_langchain_llm()  — returns LangChain BaseChatModel (for LangGraph)

Features:
  - Cooldown-aware fallback (exponential backoff per provider)
  - Multiple API keys per provider (KEY_1, KEY_2, etc.)
  - Rate-limit / billing error detection
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from .cooldown import CooldownManager

logger = logging.getLogger(__name__)

cooldown = CooldownManager()

OPENROUTER_FREE_PROVIDERS = {
    "openrouter_fast",
    "openrouter_nemotron",
    "openrouter_glm",
    "openrouter_llama",
    "openrouter_gptoss",
    "openrouter_gemma",
    "openrouter_minimax",
    "openrouter_free",
    "openrouter_qwen",
    "openrouter_qwen_coder",
    "openrouter_deepseek",
}

FALLBACK_ORDER = [
    "openrouter_fast",
    "openrouter_nemotron",
    "openrouter_glm",
    "openrouter_llama",
    "openrouter_gptoss",
    "openrouter_gemma",
    "openrouter_minimax",
    "openrouter_free",
    "openrouter_qwen",
    "openrouter_qwen_coder",
    "openrouter_kimi",
    "openrouter_deepseek",
    "openrouter",
    "azure_openai",
    "gemini",
    "groq",
    "deepseek",
    "claude",
    "openai",
]

KEY_MAP = {
    "gemini":   "GEMINI_API_KEY",
    "groq":     "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "claude":   "ANTHROPIC_API_KEY",
    "openai":   "OPENAI_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openrouter_free": "OPENROUTER_API_KEY",
    "openrouter_fast": "OPENROUTER_API_KEY",
    "openrouter_nemotron": "OPENROUTER_API_KEY",
    "openrouter_glm": "OPENROUTER_API_KEY",
    "openrouter_llama": "OPENROUTER_API_KEY",
    "openrouter_gptoss": "OPENROUTER_API_KEY",
    "openrouter_gemma": "OPENROUTER_API_KEY",
    "openrouter_minimax": "OPENROUTER_API_KEY",
    "openrouter_qwen": "OPENROUTER_API_KEY",
    "openrouter_qwen_coder": "OPENROUTER_API_KEY",
    "openrouter_kimi": "OPENROUTER_API_KEY",
    "openrouter_deepseek": "OPENROUTER_API_KEY",
}

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-31b-it")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS = {
    "openrouter": os.getenv("OPENROUTER_MODEL", "qwen/qwen3-next-80b-a3b-instruct:free"),
    "openrouter_free": "openrouter/free",
    "openrouter_fast": "nvidia/nemotron-nano-9b-v2:free",
    "openrouter_nemotron": "nvidia/nemotron-3-nano-30b-a3b:free",
    "openrouter_glm": "z-ai/glm-4.5-air:free",
    "openrouter_llama": "meta-llama/llama-3.3-70b-instruct:free",
    "openrouter_gptoss": "openai/gpt-oss-20b:free",
    "openrouter_gemma": "google/gemma-4-31b-it:free",
    "openrouter_minimax": "minimax/minimax-m2.5:free",
    "openrouter_qwen": "qwen/qwen3-next-80b-a3b-instruct:free",
    "openrouter_qwen_coder": "qwen/qwen3-coder:free",
    "openrouter_kimi": "moonshotai/kimi-k2-thinking",
    "openrouter_deepseek": "deepseek/deepseek-v4-flash:free",
}

OPENROUTER_TIMEOUT = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "25"))
OPENROUTER_MAX_TOKENS = int(os.getenv("OPENROUTER_MAX_TOKENS", "2048"))


def _get_api_key(env_var: str) -> Optional[str]:
    key = os.getenv(env_var, "")
    if key:
        return key
    for i in range(1, 10):
        key = os.getenv(f"{env_var}_{i}", "")
        if key:
            return key
    return None


def _has_api_key(env_var: str) -> bool:
    if os.getenv(env_var, ""):
        return True
    for i in range(1, 10):
        if os.getenv(f"{env_var}_{i}", ""):
            return True
    return False


def _classify_error(e: Exception) -> str:
    text = str(e).lower()
    if "429" in text or "quota" in text or "rate limit" in text or "resource_exhausted" in text:
        return "rate_limit"
    if "402" in text or "payment required" in text or "insufficient credits" in text or "credit balance" in text:
        return "billing"
    if "500" in text or "502" in text or "503" in text or "internal server error" in text or "upstream error" in text:
        return "server_error"
    if isinstance(e, (TimeoutError,)) or "timeout" in text or "timed out" in text or "readtimeout" in text:
        return "timeout"
    return "unknown"


def _is_retryable(error_type: str) -> bool:
    return error_type in ("rate_limit", "timeout", "server_error", "billing")


def _is_openrouter_free_daily_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return "free-models-per-day" in text


class LLMRouter:
    """Direct SDK LLM router with cooldown-aware automatic fallback."""

    def __init__(self, default_provider: Optional[str] = None):
        self.default_provider = default_provider or os.getenv("AGENT_PROVIDER", "gemini")

    def complete(self, messages: list[dict], system: str = "", provider: Optional[str] = None) -> str:
        target = provider or self.default_provider
        chain = _effective_fallback_chain(target)

        for name in chain:
            if not _has_api_key(KEY_MAP.get(name, "")):
                continue
            try:
                result = self._call(name, messages, system)
                cooldown.record_success(name)
                return result
            except Exception as e:
                error_type = _classify_error(e)
                logger.warning(f"Provider {name} failed ({error_type}): {e}")
                if error_type == "billing":
                    cooldown.record_failure(name, "billing")
                elif _is_retryable(error_type):
                    cooldown.record_failure(name, error_type)
                if not _is_retryable(error_type):
                    raise
                continue

        raise RuntimeError("All LLM providers failed. Check your API keys in .env")

    def _call(self, name: str, messages: list[dict], system: str) -> str:
        if name == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=_get_api_key("GEMINI_API_KEY"))
            model = genai.GenerativeModel(DEFAULT_GEMINI_MODEL, system_instruction=system or None)
            last = messages[-1]["content"] if messages else ""
            return model.generate_content(last).text

        elif name == "groq":
            from groq import Groq
            client = Groq(api_key=_get_api_key("GROQ_API_KEY"))
            all_msgs = ([{"role": "system", "content": system}] if system else []) + messages
            return client.chat.completions.create(model="llama-3.3-70b-versatile", messages=all_msgs, max_tokens=2048).choices[0].message.content

        elif name == "deepseek":
            from openai import OpenAI
            client = OpenAI(api_key=_get_api_key("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
            all_msgs = ([{"role": "system", "content": system}] if system else []) + messages
            return client.chat.completions.create(model="deepseek-chat", messages=all_msgs).choices[0].message.content

        elif name == "claude":
            import anthropic
            client = anthropic.Anthropic(api_key=_get_api_key("ANTHROPIC_API_KEY"))
            return client.messages.create(model="claude-sonnet-4-6", max_tokens=2048, system=system or "You are a helpful assistant.", messages=messages).content[0].text

        elif name == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=_get_api_key("OPENAI_API_KEY"))
            all_msgs = ([{"role": "system", "content": system}] if system else []) + messages
            return client.chat.completions.create(model="gpt-4o-mini", messages=all_msgs).choices[0].message.content

        elif name == "azure_openai":
            from openai import AzureOpenAI
            client = AzureOpenAI(
                api_key=_get_api_key("AZURE_OPENAI_API_KEY"),
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_version=AZURE_OPENAI_API_VERSION,
            )
            all_msgs = ([{"role": "system", "content": system}] if system else []) + messages
            return client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT, messages=all_msgs, max_tokens=2048
            ).choices[0].message.content

        elif name.startswith("openrouter"):
            from openai import OpenAI
            client = OpenAI(api_key=_get_api_key("OPENROUTER_API_KEY"), base_url=OPENROUTER_BASE_URL)
            all_msgs = ([{"role": "system", "content": system}] if system else []) + messages
            return client.chat.completions.create(
                model=OPENROUTER_MODELS.get(name, OPENROUTER_MODELS["openrouter"]),
                messages=all_msgs,
                extra_headers=_openrouter_headers(),
                timeout=OPENROUTER_TIMEOUT,
                max_tokens=OPENROUTER_MAX_TOKENS,
            ).choices[0].message.content

        raise ValueError(f"Unknown provider: {name}")

    def available_providers(self) -> list[str]:
        return [name for name, env in KEY_MAP.items() if _has_api_key(env)]


def build_langchain_llm(provider: Optional[str] = None):
    """Return a LangChain BaseChatModel for LangGraph tool-calling."""
    target = provider or os.getenv("AGENT_PROVIDER", "gemini")
    chain = _effective_fallback_chain(target)

    for name in chain:
        if not _has_api_key(KEY_MAP.get(name, "")):
            continue
        try:
            if name == "gemini":
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(
                    model=DEFAULT_GEMINI_MODEL,
                    google_api_key=_get_api_key("GEMINI_API_KEY"),
                    temperature=0,
                    max_retries=2,
                )
            elif name == "groq":
                from langchain_groq import ChatGroq
                return ChatGroq(model="llama-3.3-70b-versatile", api_key=_get_api_key("GROQ_API_KEY"), temperature=0)
            elif name == "deepseek":
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(model="deepseek-chat", api_key=_get_api_key("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com", temperature=0)
            elif name == "claude":
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(model="claude-sonnet-4-6", api_key=_get_api_key("ANTHROPIC_API_KEY"), temperature=0)
            elif name == "openai":
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(model="gpt-4o-mini", api_key=_get_api_key("OPENAI_API_KEY"), temperature=0)
            elif name == "azure_openai":
                from langchain_openai import AzureChatOpenAI
                return AzureChatOpenAI(
                    azure_deployment=AZURE_OPENAI_DEPLOYMENT,
                    azure_endpoint=AZURE_OPENAI_ENDPOINT,
                    api_key=_get_api_key("AZURE_OPENAI_API_KEY"),
                    api_version=AZURE_OPENAI_API_VERSION,
                    temperature=0,
                    max_retries=2,
                )
            elif name.startswith("openrouter"):
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(
                    model=OPENROUTER_MODELS.get(name, OPENROUTER_MODELS["openrouter"]),
                    api_key=_get_api_key("OPENROUTER_API_KEY"),
                    base_url=OPENROUTER_BASE_URL,
                    temperature=0,
                    max_retries=0,
                    request_timeout=OPENROUTER_TIMEOUT,
                    max_tokens=OPENROUTER_MAX_TOKENS,
                    default_headers=_openrouter_headers(),
                )
        except Exception as e:
            logger.warning(f"LangChain init failed for {name}: {e}")
            continue

    raise RuntimeError("No LLM provider available. Add at least GEMINI_API_KEY to .env (free).")


def provider_fallback_chain(provider: Optional[str] = None) -> list[str]:
    """Return the ordered list of providers that have keys and are not on cooldown."""
    target = provider or os.getenv("AGENT_PROVIDER", "gemini")
    chain = [target] + [p for p in FALLBACK_ORDER if p != target]
    available = [name for name in chain if _has_api_key(KEY_MAP.get(name, ""))]
    return cooldown.available(available)


def _effective_fallback_chain(provider: Optional[str] = None) -> list[str]:
    """Build fallback chain: target first, then cooldown-aware order."""
    target = provider or os.getenv("AGENT_PROVIDER", "gemini")
    chain = [target] + [p for p in FALLBACK_ORDER if p != target]
    available = [name for name in chain if _has_api_key(KEY_MAP.get(name, ""))]
    result = cooldown.available(available)
    if not result:
        logger.warning("All providers on cooldown! Trying anyway: %s", available[:3])
        result = available[:3]
    return result


def _openrouter_headers() -> dict[str, str]:
    return {
        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://127.0.0.1:3000"),
        "X-Title": os.getenv("OPENROUTER_APP_NAME", "AgenticWeb"),
    }
