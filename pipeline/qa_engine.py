# qa_engine.py
"""Answer questions using Gemini with strict grounding and no hallucinations."""

import os
import time

import google.genai as genai
import google.genai.types as genai_types
from dotenv import load_dotenv

from model_config import GEMINI_MODEL_POOL, MAX_RETRIES_PER_MODEL, RETRY_DELAY_SECONDS

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def build_prompt(question: str, context_chunks: list[str]) -> str:
    """Build a structured, hallucination-resistant prompt for Q&A only."""

    if not context_chunks:
        raise ValueError("No context chunks provided. Cannot build prompt without context.")

    labeled_chunks = [
        f"[Chunk {i}]\n{chunk.strip()}"
        for i, chunk in enumerate(context_chunks, start=1)
    ]
    context = "\n\n---\n\n".join(labeled_chunks)

    return f"""You are an expert AI assistant specialized in answering questions about research papers.
Your answers must be grounded exclusively in the provided context extracted from the research paper.
You have no access to outside knowledge. You must not use anything beyond what is written in the context below.

=== RESEARCH PAPER CONTEXT ===
{context}

=== USER QUESTION ===
{question}

=== INSTRUCTIONS ===

The steps below are internal reasoning instructions only.
Do not include step labels, headers, or reasoning process in your final answer.
Your answer must begin directly with the response content.

STEP 1 — IDENTIFY THE QUESTION TYPE
Determine which category this question belongs to before answering:
- Factual: asking for a specific detail, number, name, date, or metric
- Conceptual: asking to explain a method, term, or idea from the paper
- Comparative: asking to compare two approaches, models, or results
- Evaluative: asking about strengths, limitations, or contributions of the paper

STEP 2 — LOCATE RELEVANT INFORMATION
Search carefully across all provided context chunks.
If relevant information exists across multiple chunks, combine it into one coherent answer.
Prioritize these sections when present:
  Title, Abstract, Introduction, Related Work, Methodology,
  Experiments, Results, Discussion, Conclusion, Limitations.

STEP 3 — CONSTRUCT YOUR ANSWER BASED ON QUESTION TYPE

For FACTUAL questions:
  Answer directly and concisely with the exact value, name, or finding from the paper.
  Do not add context or explanation beyond what was asked.

For CONCEPTUAL questions:
  Explain clearly using only the paper's own definitions and descriptions.
  Do not import external definitions or analogies.

For COMPARATIVE questions:
  Address each side of the comparison separately before stating the contrast or conclusion.

For EVALUATIVE questions:
  Base your response entirely on what the authors themselves explicitly state in the paper.
  Do not add your own judgment.

=== HALLUCINATION CONTROL — STRICTLY ENFORCED ===
- You must NEVER use knowledge from outside the provided context.
- You must NEVER assume, speculate, or invent any detail not explicitly stated in the context.
- If the context fully answers the question: provide a complete answer.
- If the context partially answers the question: answer with what is available, then state exactly:
  "Note: The provided context does not contain complete information about [name the specific missing aspect]."
- If the context contains no relevant information at all, respond with exactly:
  "The provided document does not contain information relevant to this question."
- If the question is completely unrelated to the research paper, respond with exactly:
  "This question is unrelated to the research paper provided."
- To distinguish between the two cases above:
  If the topic of the question does not appear anywhere in the context even loosely,
  use "This question is unrelated to the research paper provided."
  If the topic appears in the context but specific details are missing,
  use the "Note:" format instead.

=== OUTPUT FORMAT RULES ===
- Write in clear, professional, academic English.
- Do not use markdown formatting or symbols such as **, *, #, or bullet points.
- Use numbered lists only when presenting multiple distinct findings or sequential steps.
- Do not repeat the same information across your answer.
- Match answer length to complexity: concise for factual questions, thorough for conceptual or evaluative ones.
- Do not begin your answer with phrases like "Based on the context" or "According to the document."
  Start directly with the answer content.

=== ANSWER ==="""


def generate_answer(prompt: str) -> str:
    """Send prompt to Gemini with model fallback and retry logic."""

    last_error = None
    total_models = len(GEMINI_MODEL_POOL)

    for model_index, model_name in enumerate(GEMINI_MODEL_POOL):
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        max_output_tokens=2048,
                        temperature=0.0,
                    ),
                )
                print(f"[{model_name}] Successfully generated answer.")
                return response.text.strip()

            except Exception as error:
                last_error = error
                error_text = str(error).lower()

                if "503" in error_text or "unavailable" in error_text:
                    print(
                        f"[{model_name}] Service unavailable "
                        f"(attempt {attempt}/{MAX_RETRIES_PER_MODEL}). "
                        f"Retrying in {RETRY_DELAY_SECONDS}s..."
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                if "429" in error_text or "quota" in error_text:
                    print(
                        f"[{model_name}] Quota exceeded "
                        f"(attempt {attempt}/{MAX_RETRIES_PER_MODEL}). "
                        f"Retrying in {RETRY_DELAY_SECONDS}s..."
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                if "404" in error_text or "not_found" in error_text or "invalid" in error_text:
                    print(f"[{model_name}] Model not found or invalid. Skipping...")
                    break

                print(f"[{model_name}] Unexpected error: {error}")
                break

        is_last_model = model_index == total_models - 1
        if not is_last_model:
            print(f"[{model_name}] Moving to next model in pool...")

    raise Exception(
        f"All {total_models} model(s) in pool failed. "
        f"Pool: {GEMINI_MODEL_POOL}. "
        f"Last error: {last_error}"
    )


def answer_question(question: str, context_chunks: list[str]) -> str:
    """
    Answer a research paper question using the provided context chunks.

    Args:
        question: The user's question about the research paper.
        context_chunks: List of relevant text chunks retrieved from the paper.

    Returns:
        A grounded answer string based strictly on the provided context.

    Raises:
        ValueError: If question is empty or context_chunks is empty.
        Exception: If all models in the pool fail.
    """
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    if not context_chunks:
        raise ValueError("Context chunks cannot be empty.")

    prompt = build_prompt(question, context_chunks)
    return generate_answer(prompt)