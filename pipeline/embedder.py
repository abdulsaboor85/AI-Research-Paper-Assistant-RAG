"""
embedder.py  -  turn text into numbers, so the computer can search by MEANING.

HOW THIS FILE WORKS (easy words)
------------------------------------------------------------
1. An "embedding model" turns a piece of text into a long list of numbers.
   Texts with a similar meaning get similar numbers.
2. We save those numbers in ChromaDB (a small database made for this).
3. Later, a question is turned into numbers too, and ChromaDB finds the
   saved chunks with the closest numbers. That is the "search".
4. The model works OFFLINE. It must be downloaded once (see the README).

FUNCTION GUIDE
------------------------------------------------------------
   collection_exists_and_has_data   is this paper already saved in the database?
   embed_and_store                  turn chunks into numbers and save them
"""

import os

os.environ["HF_HUB_OFFLINE"] = "1"          # never use the internet for the model
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
DEFAULT_COLLECTION_NAME = "research_papers_v2"
CHROMA_PATH = Path(__file__).resolve().parent.parent / "chroma_db"

print("[embedder] Loading embedding model...")
model = SentenceTransformer(EMBEDDING_MODEL_NAME)
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
print("[embedder] Model ready.")


def collection_exists_and_has_data(collection_name):
    try:
        return client.get_collection(collection_name).count() > 0
    except Exception:
        return False


def embed_and_store(chunks, collection_name=DEFAULT_COLLECTION_NAME, force=False):
    """Save the chunks of ONE paper. Skip the work if the paper is already saved."""
    if not force and collection_exists_and_has_data(collection_name):
        return

    try:
        client.delete_collection(collection_name)
    except Exception:
        pass            # it did not exist yet. That is fine.

    embeddings = model.encode(chunks, batch_size=64, show_progress_bar=False,
                              convert_to_numpy=True).tolist()

    # every chunk needs an id like "chunk_0", "chunk_1" ...
    ids = []
    metadatas = []
    for i in range(len(chunks)):
        ids.append("chunk_" + str(i))
        metadatas.append({"chunk_index": i})

    collection = client.get_or_create_collection(collection_name)
    collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)