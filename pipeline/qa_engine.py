import os
import time
from dotenv import load_dotenv
import google.genai as genai
from model_config import GEMINI_MODEL_POOL, MAX_RETRIES_PER_MODEL, RETRY_DELAY_SECONDS

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def answer_question(question, context_chunks):
    """
    Answers a question based on provided context chunks from research paper.
    
    Uses shared GEMINI_MODEL_POOL for resilience — tries models in order of
    quota availability. If one model hits rate limit or is unavailable,
    automatically falls back to the next.
    
    Args:
        question (str): The user's question
        context_chunks (list): List of text chunks from the paper
        
    Returns:
        str: The model's answer
        
    Raises:
        Exception: If all models in the pool fail
    """
    context = "\n\n".join(context_chunks)

    prompt = f"""
You are an expert research paper assistant.

Your job is to answer questions based on the research paper context provided below.

RULES:
- Use the context to give the most complete and accurate answer possible.
- If the answer is spread across multiple sections, combine them into one clear answer.
- If the question is general (like "what is this paper about"), summarize the overall topic, objective, methodology, and findings from the context.
- Only say "I couldn't find sufficient information in the paper." if the topic is truly not mentioned anywhere in the context.
- Never make up information not present in the context.
- Be detailed and clear in your answers.

FORMATTING RULES:
- Do NOT use markdown formatting like ** bold **, bullet points, or dashes.
- Do NOT use math notation like $x$ or brackets like ($s(r_i)$).
- Write in plain, clean sentences and paragraphs.
- If listing items, write them as: "1. item   2. item   3. item" on separate lines.
- Keep the answer simple and readable as plain text.

Context:
{context}

Question: {question}

Answer:
"""

    last_error = None

    # ── Try each model in the shared pool ──────────────────────────────────────
    for model_name in GEMINI_MODEL_POOL:
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"max_output_tokens": 2048}
                )
                print(f"✅ [{model_name}] Successfully answered question")
                return response.text.strip()

            except Exception as e:
                last_error = e
                error_str = str(e)

                # ── Rate limit / service unavailable — retry same model ────────
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    print(f"⚠️  [{model_name}] Service unavailable (attempt {attempt}/{MAX_RETRIES_PER_MODEL}). Retrying in {RETRY_DELAY_SECONDS}s...")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                    
                elif "429" in error_str or "quota" in error_str.lower():
                    print(f"⚠️  [{model_name}] Quota exceeded (attempt {attempt}/{MAX_RETRIES_PER_MODEL}). Retrying in {RETRY_DELAY_SECONDS}s...")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                
                # ── Model not found / invalid — skip to next model ────────────
                elif "404" in error_str or "NOT_FOUND" in error_str:
                    print(f"❌ [{model_name}] Model not found. Skipping to next model...")
                    break
                    
                elif "invalid" in error_str.lower():
                    print(f"❌ [{model_name}] Invalid model. Skipping to next model...")
                    break
                
                # ── Unexpected error — log and skip model ──────────────────────
                else:
                    print(f"❌ [{model_name}] Unexpected error: {e}")
                    break

        print(f"⏭️  Moving to next model in pool...")

    # ── All models exhausted ──────────────────────────────────────────────────
    raise Exception(
        f"All models in pool failed. Pool: {GEMINI_MODEL_POOL}. "
        f"Last error: {last_error}"
    )