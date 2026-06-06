"""
====================================================
 PATH  →  pipeline/term_explainer.py
====================================================

FYP Module  : AI-Powered Research Paper Assistant (RAG)
Feature     : Term Explainer
Author      : Abdul Saboor

Explains any term/concept in three ways:
  1. From the paper  — what this paper says about it
                       (or honestly says it's not covered)
  2. Simple words    — plain English explanation,
                       always framed in the paper's domain
  3. Real-world example — a concrete analogy or scenario
                          anyone can relate to
"""

import os
import re
import time

from google import genai

from model_config import (
    GEMINI_MODEL_POOL,
    MAX_RETRIES_PER_MODEL,
    RETRY_DELAY_SECONDS,
)


# ─────────────────────────────────────────────────────────────────────────────
#  PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_explain_prompt(term: str, chunks: list[str], paper_title: str = "") -> str:
    """
    Builds the Gemini prompt for term explanation.

    Three-part output is enforced via strict format tags so the
    frontend can parse them reliably.
    """

    if chunks:
        labeled = [
            f"[Chunk {i}]\n{chunk.strip()}"
            for i, chunk in enumerate(chunks, start=1)
        ]
        context_block = "\n\n---\n\n".join(labeled)
    else:
        context_block = "No relevant chunks were found in this paper for the given term."

    paper_hint = f'The paper is titled: "{paper_title}".' if paper_title else ""

    return f"""You are an expert academic tutor helping a university student understand research papers.

The student is reading a research paper and wants to understand the term: "{term}"

{paper_hint}

=== PAPER CONTEXT (retrieved chunks) ===
{context_block}

=== YOUR TASK ===

You must respond in EXACTLY this format — do not change the tags, do not add extra sections:

FROM_PAPER_START
[Write what this specific paper says about "{term}". Be honest:
- If the chunks clearly explain it: summarize what the paper says in 2-4 sentences.
- If the chunks only mention it without explaining: say "This paper mentions '{term}' but does not explain it in detail."
- If no relevant chunks were found: say "This term does not appear to be discussed in this paper."]
FROM_PAPER_END

SIMPLE_EXPLANATION_START
[Write a simple, plain English explanation of "{term}" in 3-5 sentences.
- Use everyday language a high school student could understand.
- NO jargon unless you immediately explain it.
- Frame it in the context of {f'the paper domain ({paper_title})' if paper_title else 'the research paper domain'}.
- Do NOT include an example here — that goes in the next section.]
SIMPLE_EXPLANATION_END

REAL_WORLD_EXAMPLE_START
[Give ONE concrete real-world example or analogy that makes "{term}" crystal clear.
- Format: start with "Example:" then the analogy/scenario.
- Make it vivid, specific, and relatable (everyday life, cooking, sports, travel, etc.).
- The example should make someone say "oh, NOW I get it!"
- 3-5 sentences maximum.
- NO jargon at all.]
REAL_WORLD_EXAMPLE_END

=== STRICT RULES ===
- Never fabricate what the paper says. Only report what is in the chunks.
- The simple explanation and real-world example must always be written even if the paper does not cover the term.
- Do not use markdown (no **, no #, no bullet points with *).
- Do not add any text outside the three tagged sections.
- Write in clear, warm, encouraging academic English.
"""


# ─────────────────────────────────────────────────────────────────────────────
#  RESPONSE PARSER
# ─────────────────────────────────────────────────────────────────────────────

def parse_explain_response(raw: str) -> dict:
    """
    Extracts the three sections from Gemini's tagged response.

    Returns:
        dict with keys:
            from_paper           (str)
            simple_explanation   (str)
            real_world_example   (str)
            parse_ok             (bool)
    """

    from_paper         = ""
    simple_explanation = ""
    real_world_example = ""

    # Extract FROM_PAPER section
    paper_match = re.search(
        r"FROM_PAPER_START\s*(.*?)\s*FROM_PAPER_END",
        raw,
        re.DOTALL,
    )
    if paper_match:
        from_paper = paper_match.group(1).strip()

    # Extract SIMPLE_EXPLANATION section
    simple_match = re.search(
        r"SIMPLE_EXPLANATION_START\s*(.*?)\s*SIMPLE_EXPLANATION_END",
        raw,
        re.DOTALL,
    )
    if simple_match:
        simple_explanation = simple_match.group(1).strip()

    # Extract REAL_WORLD_EXAMPLE section
    example_match = re.search(
        r"REAL_WORLD_EXAMPLE_START\s*(.*?)\s*REAL_WORLD_EXAMPLE_END",
        raw,
        re.DOTALL,
    )
    if example_match:
        real_world_example = example_match.group(1).strip()

    parse_ok = bool(from_paper and simple_explanation and real_world_example)

    # Graceful fallback if parsing fails
    if not parse_ok:
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        third = len(lines) // 3
        from_paper         = from_paper         or " ".join(lines[:third])         or raw.strip()
        simple_explanation = simple_explanation or " ".join(lines[third:2*third])  or raw.strip()
        real_world_example = real_world_example or " ".join(lines[2*third:])       or ""

    return {
        "from_paper":           from_paper,
        "simple_explanation":   simple_explanation,
        "real_world_example":   real_world_example,
        "parse_ok":             parse_ok,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  GEMINI CALLER
# ─────────────────────────────────────────────────────────────────────────────

def call_gemini(prompt: str, api_key: str) -> str:
    """
    Calls Gemini using the shared model pool with retry logic.

    Returns raw response text.
    Raises RuntimeError if all models fail.
    """

    client = genai.Client(api_key=api_key)
    last_error = None

    for model_name in GEMINI_MODEL_POOL:
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )

                if response and response.text:
                    return response.text.strip()

            except Exception as e:
                last_error = e
                error_msg = str(e)

                if "429" in error_msg or "quota" in error_msg.lower():
                    print(
                        f"  [TermExplainer] {model_name} quota exceeded "
                        f"(attempt {attempt}/{MAX_RETRIES_PER_MODEL}). "
                        f"Retrying in {RETRY_DELAY_SECONDS}s..."
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                elif "503" in error_msg or "UNAVAILABLE" in error_msg:
                    print(
                        f"  [TermExplainer] {model_name} unavailable "
                        f"(attempt {attempt}/{MAX_RETRIES_PER_MODEL}). "
                        f"Retrying in {RETRY_DELAY_SECONDS}s..."
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                elif "404" in error_msg or "NOT_FOUND" in error_msg.lower():
                    print(f"  [TermExplainer] {model_name} not found. Skipping...")
                    break

                else:
                    print(f"  [TermExplainer] {model_name} error: {e}")
                    break

        print(f"  [TermExplainer] Moving to next model...")

    raise RuntimeError(
        f"All Gemini models failed for term explanation. Last error: {last_error}"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def explain_term(
    term: str,
    chunks: list[str],
    api_key: str,
    paper_title: str = "",
) -> dict:
    """
    Main entry point for the Term Explainer feature.

    Args:
        term        (str)       : The term/concept to explain (e.g. "backpropagation")
        chunks      (list[str]) : Relevant chunks retrieved from ChromaDB
        api_key     (str)       : Gemini API key
        paper_title (str)       : Optional paper title for domain context

    Returns:
        dict: {
            "term"              : str,   # original term
            "from_paper"        : str,   # what the paper says (or honest fallback)
            "simple_explanation": str,   # plain English explanation
            "real_world_example": str,   # concrete analogy / scenario
            "chunks_used"       : int,   # how many chunks were found
            "found_in_paper"    : bool,  # True if relevant chunks existed
        }
    """

    if not term or not term.strip():
        raise ValueError("Term cannot be empty.")

    if not api_key:
        raise ValueError("GEMINI_API_KEY is required.")

    term = term.strip()
    found_in_paper = bool(chunks)

    prompt  = build_explain_prompt(term, chunks, paper_title)
    raw     = call_gemini(prompt, api_key)
    parsed  = parse_explain_response(raw)

    return {
        "term":               term,
        "from_paper":         parsed["from_paper"],
        "simple_explanation": parsed["simple_explanation"],
        "real_world_example": parsed["real_world_example"],
        "chunks_used":        len(chunks),
        "found_in_paper":     found_in_paper,
    }