import os
from dotenv import load_dotenv
import google.genai as genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def answer_question(question, context_chunks):
    context = "\n\n".join(context_chunks)
    
    prompt = f"""You are a helpful research assistant. 
Answer the question based ONLY on the context provided below.
If the answer is not in the context, say "I couldn't find this in the paper."

Context:
{context}

Question: {question}

Answer:"""
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text.strip()