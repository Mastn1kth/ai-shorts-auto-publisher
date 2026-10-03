"""Local LLM backends. The UI can choose a provider per job."""
import os

from ..config import (
    GEMINI_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    require_gemini_key,
    require_openai_key,
)


def call_openai_llm(prompt: str) -> str:
    """OpenAI Chat Completions backend used by --mode local."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = OpenAI(api_key=require_openai_key())
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def call_gemini_llm(prompt: str) -> str:
    """Gemini backend used by --mode local when LLM_PROVIDER=gemini."""
    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = genai.Client(api_key=require_gemini_key())
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": 8192,
        },
    )
    return response.text or ""


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = (LLM_PROVIDER or "openai").strip().lower()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai' or 'gemini'."
    )


OPENAI_COMPATIBLE_URLS = {
    "openai": None,
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def make_llm(provider: str, model: str, api_key: str = "", base_url: str = ""):
    """Return a callable for one job without changing process-wide environment."""
    provider = provider.strip().lower()
    model = model.strip()
    if not model:
        raise ValueError("Model name is required")
    if provider == "gemini":
        key = api_key.strip() or os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise ValueError("Gemini API key is required")

        def gemini(prompt: str) -> str:
            from google import genai  # type: ignore

            response = genai.Client(api_key=key).models.generate_content(
                model=model,
                contents=prompt,
                config={"temperature": 0.2, "response_mime_type": "application/json", "max_output_tokens": 8192},
            )
            return response.text or ""

        return gemini

    if provider not in {*OPENAI_COMPATIBLE_URLS, "custom"}:
        raise ValueError("Unsupported AI provider")
    key_env = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "groq": "GROQ_API_KEY"}
    key = api_key.strip() or os.getenv(key_env.get(provider, ""), "").strip()
    if not key and provider != "custom":
        raise ValueError(f"{provider} API key is required")
    endpoint = base_url.strip() if provider == "custom" else OPENAI_COMPATIBLE_URLS[provider]
    if provider == "custom" and not endpoint:
        raise ValueError("Custom API base URL is required")

    def compatible(prompt: str) -> str:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=key or "local", base_url=endpoint, timeout=120)
        response = client.chat.completions.create(
            model=model, temperature=0.2, messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content or ""

    return compatible
