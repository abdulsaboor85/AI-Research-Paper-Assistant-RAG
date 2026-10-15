"""Loads the embedding model + ChromaDB ONCE, and stores paper chunks."""

import os

os.environ["HF_HUB_OFFLINE"] = "1"        # don't touch the network
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
CHROMA_PATH = Path(__file__).resolve().parent.parent / "chroma_db"

print("[embedder] Loading embedding model...")
model = SentenceTransformer(EMBEDDING_MODEL_NAME)
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
print("[embedder] Model ready.")


def collection_exists_and_has_data(collection_name: str) -> bool:
    try:
        return client.get_collection(collection_name).count() > 0
    except Exception:
        return False


def embed_and_store(chunks: list[str], collection_name: str) -> None:
    """Replace the collection with fresh embeddings of `chunks`."""
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass  # didn't exist yet

    collection = client.create_collection(collection_name)
    embeddings = model.encode(
        chunks, batch_size=64, show_progress_bar=False, convert_to_numpy=True
    ).tolist()

    collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=[f"chunk_{i}" for i in range(len(chunks))],
        metadatas=[{"chunk_index": i} for i in range(len(chunks))],
    )
    print(f"[embedder] Stored {len(chunks)} chunks in '{collection_name}'.")