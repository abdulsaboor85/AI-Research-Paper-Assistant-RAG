from sentence_transformers import SentenceTransformer
import chromadb
import os

model = SentenceTransformer("all-MiniLM-L6-v2")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
client = chromadb.PersistentClient(path=os.path.join(BASE_DIR, "chroma_db"))

def get_or_create_collection(collection_name="research_papers"):
    collection = client.get_or_create_collection(name=collection_name)
    return collection

def embed_and_store(chunks, collection_name="research_papers"):
    collection = get_or_create_collection(collection_name)
    
    client.delete_collection(collection_name)
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