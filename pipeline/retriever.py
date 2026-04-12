from sentence_transformers import SentenceTransformer
import chromadb
import os

model = SentenceTransformer("all-MiniLM-L6-v2")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
client = chromadb.PersistentClient(path=os.path.join(BASE_DIR, "chroma_db"))

def retrieve_relevant_chunks(query, collection_name="research_papers", top_k=5):
    collection = client.get_or_create_collection(collection_name)
    
    query_embedding = model.encode([query]).tolist()
    
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )
    
    chunks = results["documents"][0]
    return chunks