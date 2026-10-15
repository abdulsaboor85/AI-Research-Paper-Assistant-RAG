"""Term Explainer: what the paper says + simple words + a real-world example."""

import re

from model_config import call_gemini

SECTIONS = ("FROM_PAPER", "SIMPLE_EXPLANATION", "REAL_WORLD_EXAMPLE")


def build_explain_prompt(term: str, chunks: list[str], paper_title: str = "") -> str:
    if chunks:
        context = "\n\n---\n\n".join(
            f"[Chunk {i}]\n{chunk.strip()}" for i, chunk in enumerate(chunks, start=1)
        )
    else:
        context = "No relevant chunks were found in this paper for the given term."

    paper_hint = f'The paper is titled: "{paper_title}".' if paper_title else ""
    domain = f"the paper domain ({paper_title})" if paper_title else "the research paper domain"

    return f"""You are an expert academic tutor helping a university student understand research papers.
The student wants to understand the term: "{term}"
{paper_hint}

=== PAPER CONTEXT (retrieved chunks) ===
{context}

=== YOUR TASK ===
Respond in EXACTLY this format. Do not change the tags or add sections:

FROM_PAPER_START
[What this paper says about "{term}". Be honest:
- Chunks explain it clearly: summarize in 2-4 sentences.
- Chunks only mention it: say "This paper mentions '{term}' but does not explain it in detail."
- No relevant chunks: say "This term does not appear to be discussed in this paper."]
FROM_PAPER_END

SIMPLE_EXPLANATION_START
[A plain English explanation of "{term}" in 3-5 sentences.
- Everyday language a high school student understands. No jargon unless explained.
- Frame it in {domain}.
- Do NOT include an example here.]
SIMPLE_EXPLANATION_END

REAL_WORLD_EXAMPLE_START
[ONE concrete real-world example or analogy. Start with "Example:".
- Vivid, specific, relatable (everyday life, cooking, sports, travel...).
- 3-5 sentences. No jargon at all.]
REAL_WORLD_EXAMPLE_END

=== STRICT RULES ===
- Never invent what the paper says. Only report what is in the chunks.
- The simple explanation and example must be written even if the paper does not cover the term.
- No markdown (no **, no #, no * bullets). No text outside the three tagged sections.
- Write in clear, warm, encouraging academic English.
"""


def parse_explain_response(raw: str) -> dict:
    """Pull the three tagged sections out of Gemini's reply."""
    parts = {}
    for name in SECTIONS:
        match = re.search(rf"{name}_START\s*(.*?)\s*{name}_END", raw, re.DOTALL)
        parts[name] = match.group(1).strip() if match else ""

    if not all(parts.values()):  # tags missing -> split the text in 3 as a fallback
        lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        third = len(lines) // 3
        fallback = (
            " ".join(lines[:third]) or raw.strip(),
            " ".join(lines[third:2 * third]) or raw.strip(),
            " ".join(lines[2 * third:]),
        )
        for name, text in zip(SECTIONS, fallback):
            parts[name] = parts[name] or text

    return {
        "from_paper": parts["FROM_PAPER"],
        "simple_explanation": parts["SIMPLE_EXPLANATION"],
        "real_world_example": parts["REAL_WORLD_EXAMPLE"],
    }


def explain_term(term: str, chunks: list[str], api_key: str, paper_title: str = "") -> dict:
    term = (term or "").strip()
    if not term:
        raise ValueError("Term cannot be empty.")

    raw = call_gemini(build_explain_prompt(term, chunks, paper_title), api_key, tag="TermExplainer")

    return {
        "term": term,
        **parse_explain_response(raw),
        "chunks_used": len(chunks),
        "found_in_paper": bool(chunks),
    }