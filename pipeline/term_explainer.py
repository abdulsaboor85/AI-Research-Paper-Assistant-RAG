"""
term_explainer.py  -  explain a word or phrase from the paper.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. The retriever finds the chunks of the paper that talk about the term.
2. We ask Gemini for THREE parts:
     FROM_PAPER          what THIS paper says about the term (honest: only what is in the chunks)
     SIMPLE_EXPLANATION  the term in everyday words
     REAL_WORLD_EXAMPLE  an example or comparison from daily life
3. We split the answer into the three parts and return them.
If the paper does not talk about the term, the simple explanation and the example
are still written (and "found_in_paper" is False).

FUNCTION GUIDE
------------------------------------------------------------
   build_prompt    write the instruction we send to Gemini
   explain_term    the main function
"""

from model_config import generate_text, parse_tagged_sections

TAGS = ["FROM_PAPER", "SIMPLE_EXPLANATION", "REAL_WORLD_EXAMPLE"]


def build_prompt(term, chunks, paper_title):
    if chunks:
        labeled = []
        number = 1
        for chunk in chunks:
            labeled.append("[Chunk " + str(number) + "]\n" + chunk.strip())
            number += 1
        context_block = "\n\n---\n\n".join(labeled)
    else:
        context_block = "No relevant chunks were found in this paper for the given term."

    paper_hint = ""
    domain = "the research paper domain"
    if paper_title:
        paper_hint = 'The paper is titled: "' + paper_title + '".'
        domain = "the paper domain (" + paper_title + ")"

    return f"""You are an expert academic tutor helping a university student understand research papers.

The student wants to understand the term: "{term}"

{paper_hint}

=== PAPER CONTEXT (retrieved chunks) ===
{context_block}

=== YOUR TASK ===
Answer in EXACTLY this format. Do not change the tags. Do not add other sections.

FROM_PAPER_START
[What this specific paper says about "{term}". Be honest:
- Chunks explain it clearly: summarize in 2-4 sentences.
- Chunks only mention it: say "This paper mentions '{term}' but does not explain it in detail."
- No relevant chunks: say "This term does not appear to be discussed in this paper."]
FROM_PAPER_END

SIMPLE_EXPLANATION_START
[A simple, plain English explanation of "{term}" in 3-5 sentences.
- Everyday language a high school student understands.
- No jargon unless you explain it right away.
- Frame it in the context of {domain}.
- Do NOT give an example here. That is the next section.]
SIMPLE_EXPLANATION_END

REAL_WORLD_EXAMPLE_START
[ONE concrete real-world example or comparison that makes "{term}" very clear.
- Start with "Example:" and then the scenario.
- Vivid, specific, relatable (everyday life, cooking, sports, travel...).
- 3-5 sentences. No jargon at all.]
REAL_WORLD_EXAMPLE_END

=== STRICT RULES ===
- Never invent what the paper says. Only report what is in the chunks.
- Always write the simple explanation and the example, even if the paper does not cover the term.
- No markdown (no **, no #, no * bullets).
- No text outside the three tagged sections.
- Write in clear, warm, encouraging English."""


def explain_term(term, chunks, api_key, paper_title=""):
    term = (term or "").strip()
    if not term:
        raise ValueError("Term cannot be empty.")

    answer = generate_text(build_prompt(term, chunks, paper_title), api_key)
    sections, ok = parse_tagged_sections(answer, TAGS)

    return {
        "term": term,
        "from_paper": sections["FROM_PAPER"],
        "simple_explanation": sections["SIMPLE_EXPLANATION"],
        "real_world_example": sections["REAL_WORLD_EXAMPLE"],
        "chunks_used": len(chunks),
        "found_in_paper": bool(chunks),
    }