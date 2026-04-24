from sentence_transformers import SentenceTransformer
import chromadb
import os

# Better embedding model
model = SentenceTransformer("BAAI/bge-base-en-v1.5")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
client = chromadb.PersistentClient(path=os.path.join(BASE_DIR, "chroma_db"))

def get_or_create_collection(collection_name="research_papers"):
    return client.get_or_create_collection(name=collection_name)

def embed_and_store(chunks, collection_name="research_papers_v2"):
    # Reset collection (fresh upload each time)
    try:
        client.delete_collection(collection_name)
    except:
        pass

    collection = client.get_or_create_collection(collection_name)

    embeddings = model.encode(chunks).tolist()
    ids = [f"chunk_{i}" for i in range(len(chunks))]

    collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=ids
    )

    print(f"✅ Stored {len(chunks)} chunks in ChromaDB")
    return collection