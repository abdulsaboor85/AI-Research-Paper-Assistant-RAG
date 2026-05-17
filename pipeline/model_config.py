"""
====================================================
 PATH  →  pipeline/model_config.py
====================================================

FYP Module  : AI-Powered Research Paper Assistant (RAG)
Feature     : Shared Model Pool Configuration
Author      : Abdul Saboor

Centralized Gemini model pool configuration used by:
  - qa_engine.py (QA answering)
  - difficulty_scorer.py (Difficulty analysis)

Updated based on current API quotas (May 2026):
https://aistudio.google.com/

Ordered by RPD (Requests Per Day) — highest first.
If one model hits quota or fails, the next is tried automatically.
"""

# ── Gemini Model Pool ─────────────────────────────────────────────────────────
# Ordered by free tier RPD (requests per day) — highest first.
#
# Your current free quotas:
#   gemini-3.1-flash-lite   →  500 RPD  ← PRIMARY (try first)
#   gemini-2.5-flash        →   23 RPD  ← HIGH QUOTA
#   gemini-3-flash          →   20 RPD
#   gemini-2.5-flash-lite   →   20 RPD  ← FALLBACK
#
GEMINI_MODEL_POOL = [
    "gemini-3.1-flash-lite",    # 500 RPD — most generous free quota
    "gemini-2.5-flash",         # 23 RPD — second choice
    "gemini-3-flash",           # 20 RPD
    "gemini-2.5-flash-lite",    # 20 RPD — last resort
]

# ── Model metadata (for logging/debugging) ────────────────────────────────────
MODEL_METADATA = {
    "gemini-3.1-flash-lite": {"rpm": 15, "tpm": 250000, "rpd": 500, "type": "Text-out"},
    "gemini-2.5-flash": {"rpm": 2, "tpm": 250000, "rpd": 23, "type": "Text-out"},
    "gemini-3-flash": {"rpm": 5, "tpm": 250000, "rpd": 20, "type": "Text-out"},
    "gemini-2.5-flash-lite": {"rpm": 10, "tpm": 250000, "rpd": 20, "type": "Text-out"},
}

# ── Retry configuration ───────────────────────────────────────────────────────
MAX_RETRIES_PER_MODEL = 3
RETRY_DELAY_SECONDS = 1
