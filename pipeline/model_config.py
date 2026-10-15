"""Shared Gemini settings + ONE helper that every module uses to call Gemini."""

import time

from google import genai
from google.genai import types

GEMINI_MODEL_POOL = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash",
    "gemini-2.5-flash-lite",
]

MAX_RETRIES_PER_MODEL = 3
RETRY_DELAY_SECONDS = 1

# Temporary problems: wait and retry the same model.
_TEMPORARY_ERRORS = ("429", "quota", "503", "unavailable")


def call_gemini(prompt: str, api_key: str, *, temperature: float | None = None,
                max_output_tokens: int | None = None, tag: str = "Gemini") -> str:
    """Send a prompt to Gemini. Retries on temporary errors, then tries the next model."""
    if not api_key:
        raise ValueError("No Gemini API key configured. Add one via the gear icon or .env")

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    last_error = None

    for model in GEMINI_MODEL_POOL:
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                response = client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
                if response.text:
                    return response.text.strip()
                break  # empty answer -> try the next model

            except Exception as error:
                last_error = error
                print(f"[{tag}] {model} (attempt {attempt}/{MAX_RETRIES_PER_MODEL}): {str(error)[:200]}")
                if not any(word in str(error).lower() for word in _TEMPORARY_ERRORS):
                    break  # not temporary -> next model
                time.sleep(RETRY_DELAY_SECONDS)

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")