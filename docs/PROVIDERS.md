# LLM Providers

## Recommended Free Options

```bash
# OpenRouter - recommended for this web-agent workflow
OPENROUTER_API_KEY=
AGENT_PROVIDER=openrouter_qwen

# Gemini / Gemma via Google AI Studio
GEMINI_API_KEY=
AGENT_PROVIDER=gemini
```

## OpenRouter Models

| Provider ID | Model | Notes |
|---|---|---|
| `openrouter_qwen` | `qwen/qwen3-next-80b-a3b-instruct:free` | Recommended first choice for web-agent workflows |
| `openrouter_qwen_coder` | `qwen/qwen3-coder:free` | Stronger coding/task-planning fallback |
| `openrouter_deepseek` | `deepseek/deepseek-v4-flash:free` | Free DeepSeek V4 option |
| `openrouter_fast` | `nvidia/nemotron-nano-9b-v2:free` | Fast tool-capable free fallback |
| `openrouter_nemotron` | `nvidia/nemotron-3-nano-30b-a3b:free` | Tool-capable free fallback |
| `openrouter_glm` | `z-ai/glm-4.5-air:free` | Tool-capable free fallback |
| `openrouter_llama` | `meta-llama/llama-3.3-70b-instruct:free` | Strong general free fallback |
| `openrouter_gptoss` | `openai/gpt-oss-20b:free` | Lightweight free fallback |
| `openrouter_gemma` | `google/gemma-4-31b-it:free` | Gemma via OpenRouter free endpoint |
| `openrouter_minimax` | `minimax/minimax-m2.5:free` | Another current free fallback |
| `openrouter_free` | `openrouter/free` | Lets OpenRouter pick an available free model |
| `openrouter_kimi` | `moonshotai/kimi-k2-thinking` | Strong reasoning, not currently free in OpenRouter catalog |
| `openrouter` | value of `OPENROUTER_MODEL` | Custom OpenRouter model ID |

OpenRouter uses the OpenAI-compatible endpoint `https://openrouter.ai/api/v1`.

## Other Providers

| Provider ID | Model | Key |
|---|---|---|
| `gemini` | `GEMINI_MODEL` from `.env` | `GEMINI_API_KEY` |
| `groq` | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| `deepseek` | `deepseek-chat` (V4 Flash) | `DEEPSEEK_API_KEY` |
| `claude` | Claude Sonnet | `ANTHROPIC_API_KEY` |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` |

Switch in the Web UI dropdown, Telegram with `/provider openrouter_qwen`, or `.env` with `AGENT_PROVIDER=openrouter_qwen`.
