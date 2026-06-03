
from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME    = "BAAI/bge-base-en-v1.5"
DEFAULT_COLLECTION_NAME = "research_papers_v2"

BASE_DIR    = Path(__file__).resolve().parent.parent
CHROMA_PATH = BASE_DIR / "chroma_db"

print("[embedder] Loading SentenceTransformer model (first time only)...")
model  = SentenceTransformer(EMBEDDING_MODEL_NAME)
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
print("[embedder] Model ready.")


def collection_exists_and_has_data(collection_name: str) -> bool:
    try:
        col = client.get_collection(collection_name)
        return col.count() > 0
    except Exception:
        return False


def get_or_create_collection(collection_name: str = "research_papers"):
    return client.get_or_create_collection(name=collection_name)


def embed_and_store(
    chunks: list[str],
    collection_name: str = DEFAULT_COLLECTION_NAME,
    force: bool = False,
) -> None:
    """
    Embed and store chunks. Skips if already indexed (unless force=True).
    Uses batch encoding - much faster than default.
    """
    if not force and collection_exists_and_has_data(collection_name):
        print(f"[embedder] '{collection_name}' already indexed - skipping.")
        return

    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.get_or_create_collection(collection_name)

    # batch_size=64 is much faster than default
    embeddings = model.encode(
        chunks,
        batch_size=64,
        show_progress_bar=False,
        convert_to_numpy=True,
    ).tolist()

    ids       = [f"chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"chunk_index": i} for i in range(len(chunks))]

    collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas,
    )
    print(f"[embedder] Stored {len(chunks)} chunks in '{collection_name}'.")