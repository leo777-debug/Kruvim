"""LLM providers. Every model call in Kruvim goes through `make_llm(...)`."""
from __future__ import annotations

from .base import BaseLLM, LLMAuthError, LLMError, ProviderSettings, Usage, extract_json  # noqa: F401

PRESETS = {
    "dryrun": {"label": "Dry run (no model)", "provider": "dryrun", "base_url": "", "local": True,
               "voice_model": "", "report_model": "", "vision_model": ""},
    "deepseek": {"label": "DeepSeek", "provider": "openai", "base_url": "https://api.deepseek.com/v1", "local": False,
                 "voice_model": "deepseek-flash", "report_model": "deepseek-v4-pro", "vision_model": "deepseek-flash"},
    "openrouter": {"label": "OpenRouter", "provider": "openai", "base_url": "https://openrouter.ai/api/v1", "local": False,
                   "voice_model": "", "report_model": "", "vision_model": ""},
    "openai": {"label": "OpenAI", "provider": "openai", "base_url": "https://api.openai.com/v1", "local": False,
               "voice_model": "", "report_model": "", "vision_model": ""},
    "anthropic": {"label": "Anthropic (Claude)", "provider": "anthropic", "base_url": "", "local": False,
                  "voice_model": "claude-opus-5-5", "report_model": "claude-opus-5-5", "vision_model": "claude-opus-5-5"},
    "groq": {"label": "Groq", "provider": "openai", "base_url": "https://api.groq.com/openai/v1", "local": False,
             "voice_model": "", "report_model": "", "vision_model": ""},
    "together": {"label": "Together AI", "provider": "openai", "base_url": "https://api.together.xyz/v1", "local": False,
                 "voice_model": "", "report_model": "", "vision_model": ""},
    "custom": {"label": "Other OpenAI-compatible", "provider": "openai", "base_url": "", "local": False,
               "voice_model": "", "report_model": "", "vision_model": ""},
    "ollama": {"label": "Ollama (local)", "provider": "openai", "base_url": "http://localhost:11434/v1", "local": True,
               "voice_model": "", "report_model": "", "vision_model": ""},
    "lmstudio": {"label": "LM Studio (local)", "provider": "openai", "base_url": "http://localhost:1234/v1", "local": True,
                 "voice_model": "", "report_model": "", "vision_model": ""},
    "llamacpp": {"label": "llama.cpp server (local)", "provider": "openai", "base_url": "http://localhost:8080/v1", "local": True,
                 "voice_model": "", "report_model": "", "vision_model": ""},
    "vllm": {"label": "vLLM (self-hosted)", "provider": "openai", "base_url": "http://localhost:8000/v1", "local": True,
             "voice_model": "", "report_model": "", "vision_model": ""},
}


class DryRunLLM(BaseLLM):
    """Marker provider: services check `is_dry` and use their deterministic, labelled stand-ins."""
    name = "dryrun"
    is_dry = True

    def has_vision(self) -> bool:
        return False

    def model_for(self, role: str) -> str:
        return "dry-run"

    async def complete(self, **kw):
        raise LLMError("dry run has no model")


def make_llm(s: ProviderSettings) -> BaseLLM:
    if s.provider == "openai":
        from .openai_compat import OpenAICompatLLM
        return OpenAICompatLLM(s)
    if s.provider == "anthropic":
        from .anthropic_provider import AnthropicLLM
        return AnthropicLLM(s)
    return DryRunLLM(s)
