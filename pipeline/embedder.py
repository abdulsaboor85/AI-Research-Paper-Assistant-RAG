from sentence_transformers import SentenceTransformer
import chromadb

# Load the embedding model once (reused across calls)
model = SentenceTransformer("all-MiniLM-L6-v2")

# Initialize ChromaDB client (stores data locally)
client = chromadb.PersistentClient(path="./chroma_db")

def get_or_create_collection(collection_name="research_papers"):
    collection = client.get_or_create_collection(name=collection_name)
    return collection

def embed_and_store(chunks, collection_name="research_papers"):
    collection = get_or_create_collection(collection_name)
    
    # Clear old data so each new PDF starts fresh
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