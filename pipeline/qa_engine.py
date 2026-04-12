import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel("gemini-1.5-flash")

def answer_question(question, context_chunks):
    context = "\n\n".join(context_chunks)
    
    prompt = f"""You are a helpful research assistant. 
Answer the question based ONLY on the context provided below.
If the answer is not in the context, say "I couldn't find this in the paper."

Context:
{context}

Question: {question}

Answer:"""
    
    response = model.generate_content(prompt)
    return response.text.strip()