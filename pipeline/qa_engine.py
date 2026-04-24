import os
import time
from dotenv import load_dotenv
import google.genai as genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]

def answer_question(question, context_chunks):
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

    for model_name in MODELS:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"max_output_tokens": 2048}
                )
                return response.text.strip()

            except Exception as e:
                last_error = e
                error_str = str(e)

                if "503" in error_str or "UNAVAILABLE" in error_str or "429" in error_str:
                    print(f"⚠️  {model_name} busy (attempt {attempt + 1}/3). Retrying in 1s...")
                    time.sleep(1)
                    continue
                elif "404" in error_str or "NOT_FOUND" in error_str:
                    print(f"❌ {model_name} not found in your API. Skipping...")
                    break
                else:
                    raise

        print(f"⏭️  Moving to next model...")

    raise Exception(f"All models failed. Last error: {last_error}")