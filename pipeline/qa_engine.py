"""Answer questions about a paper using Gemini, strictly from the retrieved chunks."""

from model_config import call_gemini


def build_prompt(question: str, context_chunks: list[str]) -> str:
    context = "\n\n---\n\n".join(
        f"[Chunk {i}]\n{chunk.strip()}" for i, chunk in enumerate(context_chunks, start=1)
    )

    return f"""You are an expert AI assistant specialized in answering questions about research papers.
Your answer must be grounded exclusively in the context below. You have no outside knowledge.

=== RESEARCH PAPER CONTEXT ===
{context}

=== USER QUESTION ===
{question}

=== HOW TO ANSWER (internal reasoning, never show these steps) ===
Decide the question type, find the relevant chunks, combine them, then answer:
- Factual: answer directly with the exact value, name, or finding. Nothing extra.
- Conceptual: explain using only the paper's own definitions. No outside analogies.
- Comparative: describe each side separately, then state the contrast.
- Evaluative: report only what the authors explicitly state. No own judgment.

=== HALLUCINATION CONTROL (STRICT) ===
- NEVER use outside knowledge. NEVER assume or invent details.
- Context fully answers the question: give a complete answer.
- Context partly answers it: answer with what exists, then add exactly:
  "Note: The provided context does not contain complete information about [the missing aspect]."
- Topic appears in the context but has no relevant info: respond exactly:
  "The provided document does not contain information relevant to this question."
- Topic does not appear in the context at all: respond exactly:
  "This question is unrelated to the research paper provided."

=== OUTPUT FORMAT ===
- Clear, professional, academic English. Start directly with the answer
  (never "Based on the context" or "According to the document").
- Light markdown: **bold** for key terms and numbers, numbered lists for steps,
  bullets for unordered items, short paragraphs. Use a heading (## ) only for 2+ sub-topics.
- A one-line factual answer should be plain text. Do not repeat yourself.
- Short for factual questions, thorough for conceptual or evaluative ones.

=== ANSWER ==="""


def answer_question(question: str, context_chunks: list[str], api_key: str) -> str:
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")
    if not context_chunks:
        raise ValueError("Context chunks cannot be empty.")

    prompt = build_prompt(question, context_chunks)
    return call_gemini(prompt, api_key, temperature=0.0, max_output_tokens=2048, tag="QA")