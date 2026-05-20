"""Shared Gemini model configuration."""

GEMINI_MODEL_POOL = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash",
    "gemini-2.5-flash-lite",
]

MAX_RETRIES_PER_MODEL = 3
RETRY_DELAY_SECONDS = 1
