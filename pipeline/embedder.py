"""Create embeddings and store chunks in ChromaDB."""

from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME = "BAAI/bge-base-en-v1.5"
DEFAULT_COLLECTION_NAME = "research_papers_v2"

BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_PATH = BASE_DIR / "chroma_db"

model = SentenceTransformer(EMBEDDING_MODEL_NAME)
client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def get_or_create_collection(collection_name: str = "research_papers"):
    return client.get_or_create_collection(name=collection_name)


def embed_and_store(chunks: list[str], collection_name: str = DEFAULT_COLLECTION_NAME):
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.get_or_create_collection(collection_name)
    embeddings = model.encode(chunks).tolist()
    ids = [f"chunk_{index}" for index in range(len(chunks))]
    metadatas = [{"chunk_index": index} for index in range(len(chunks))]

    collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas,
    )

    print(f"✅ Stored {len(chunks)} chunks in ChromaDB")
    return collection
