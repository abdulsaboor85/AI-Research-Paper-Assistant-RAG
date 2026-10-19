"""
model_config.py  -  how we talk to Google Gemini (the AI). Every other file uses it.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. We have a LIST of Gemini models.
2. generate_text() sends your text (the "prompt") to the first model.
3. If that model is busy (error 429 / 503), we wait 1 second and try again (3 times).
4. If it still fails, we try the NEXT model in the list.
5. If all models fail, we raise an error.
So the app keeps working even when one model is overloaded.

FUNCTION GUIDE
------------------------------------------------------------
   generate_text          send a prompt to Gemini, get the answer as text
   parse_tagged_sections  split an answer into parts marked like  NAME_START ... NAME_END
"""

import os
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# Models to try, in this order
GEMINI_MODEL_POOL = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash",
    "gemini-2.5-flash-lite",
]
MAX_RETRIES_PER_MODEL = 3
RETRY_DELAY_SECONDS = 1

# If the error text has one of these words, the model is only busy. Try again.
BUSY_WORDS = ["429", "quota", "503", "unavailable"]


def generate_text(prompt, api_key=None, **settings):
    """Send a prompt to Gemini and return the answer text.

    **settings means extra options are allowed, for example:
        temperature=0.0, max_output_tokens=2048, response_mime_type="application/json"
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No Gemini API key configured. Add one with the gear icon or in .env")

    client = genai.Client(api_key=api_key)
    config = None
    if settings:
        config = types.GenerateContentConfig(**settings)
    last_error = None

    for model in GEMINI_MODEL_POOL:
        for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                response = client.models.generate_content(model=model, contents=prompt, config=config)
                if response and response.text:
                    return response.text.strip()
            except Exception as error:
                last_error = error
                error_text = str(error).lower()

                is_busy = False
                for word in BUSY_WORDS:
                    if word in error_text:
                        is_busy = True

                if is_busy:
                    print("[Gemini]", model, "is busy (try", attempt, "), waiting...")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue            # try the same model again
                print("[Gemini]", model, "skipped:", error)
                break                   # a real error: go to the next model

    raise RuntimeError("All Gemini models failed. Last error: " + str(last_error))


def parse_tagged_sections(raw_text, tags):
    """Find the parts of an answer that look like:
          NAME_START
          ...text...
          NAME_END
    "tags" is a list of three names. Returns (sections, parse_ok).
    If a part is missing, the answer is cut into three pieces as a backup."""
    sections = {}
    for tag in tags:
        match = re.search(tag + r"_START\s*(.*?)\s*" + tag + "_END", raw_text, re.DOTALL)
        if match:
            sections[tag] = match.group(1).strip()
        else:
            sections[tag] = ""

    parse_ok = True
    for tag in tags:
        if sections[tag] == "":
            parse_ok = False

    if not parse_ok:
        lines = []
        for line in raw_text.strip().split("\n"):
            if line.strip():
                lines.append(line.strip())
        third = max(1, len(lines) // 3)
        pieces = [lines[:third], lines[third:2 * third], lines[2 * third:]]

        for i in range(len(tags)):
            tag = tags[i]
            if sections[tag]:
                continue
            guess = " ".join(pieces[i])
            is_last = (i == len(tags) - 1)
            if guess:
                sections[tag] = guess
            elif not is_last:
                sections[tag] = raw_text.strip()

    return sections, parse_ok