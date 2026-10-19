"""
qa_engine.py  -  answer a question using ONLY the paper (so the AI cannot make things up).

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. The retriever gives us the best chunks of the paper.
2. build_prompt() writes ONE long instruction for Gemini. It contains:
     the chunks, the question, and strict rules ("only use these chunks").
3. answer_question() sends that instruction to Gemini and returns the answer.
temperature=0 means "do not be creative", so the answer stays factual.

FUNCTION GUIDE
------------------------------------------------------------
   build_prompt      write the instruction text we send to Gemini
   answer_question   send it and return Gemini's answer
"""

from model_config import generate_text


def build_prompt(question, context_chunks):
    if not context_chunks:
        raise ValueError("No context chunks provided. Cannot build prompt without context.")

    labeled = []
    number = 1
    for chunk in context_chunks:
        labeled.append("[Chunk " + str(number) + "]\n" + chunk.strip())
        number += 1
    context = "\n\n---\n\n".join(labeled)

    return f"""You are an expert assistant for questions about research papers.
Answer ONLY from the paper context below. You have no outside knowledge.

=== RESEARCH PAPER CONTEXT ===
{context}

=== USER QUESTION ===
{question}

=== HOW TO ANSWER ===
Think silently first. Do NOT write these steps in your answer.
1. Decide the question type: factual (a number, name, date), conceptual (explain an idea),
   comparative (compare two things), or evaluative (strengths, limits, contributions).
2. Search ALL the chunks and combine what you find.
3. Answer by type:
   - factual: short and exact.
   - conceptual: use only the paper's own definitions. No outside analogies.
   - comparative: describe each side, then the difference.
   - evaluative: use only what the authors say. Add no opinion of your own.

=== NEVER MAKE THINGS UP ===
- Never use outside knowledge. Never guess or invent details.
- Context answers the question fully: give a full answer.
- Context answers only part: answer that part, then write exactly:
  "Note: The provided context does not contain complete information about [the missing part]."
- The topic appears in the context but the details are missing: use the "Note:" sentence above.
- The context has nothing relevant: write exactly:
  "The provided document does not contain information relevant to this question."
- The question is unrelated to the paper (its topic is nowhere in the context): write exactly:
  "This question is unrelated to the research paper provided."

=== FORMAT ===
- Clear, professional, academic English. Start directly with the answer.
  Do not start with "Based on the context" or "According to the document".
- Light markdown: **bold** for key terms and numbers, numbered lists for steps,
  bullets for lists, short paragraphs. Use a ## heading only when there are 2+ sub-topics.
- A one-line factual answer should be plain text. Do not repeat yourself.
- Short for factual questions, thorough for conceptual or evaluative ones.

=== ANSWER ==="""


def answer_question(question, context_chunks, api_key=None):
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")
    if not context_chunks:
        raise ValueError("Context chunks cannot be empty.")

    prompt = build_prompt(question, context_chunks)
    return generate_text(prompt, api_key, max_output_tokens=2048, temperature=0.0)