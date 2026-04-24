from sentence_transformers import SentenceTransformer
import chromadb
import os

model = SentenceTransformer("BAAI/bge-base-en-v1.5")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
client = chromadb.PersistentClient(path=os.path.join(BASE_DIR, "chroma_db"))

def retrieve_relevant_chunks(query, collection_name="research_papers_v2", top_k=10):
    collection = client.get_or_create_collection(collection_name)

    query_embedding = model.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )

    chunks = results["documents"][0]
    scores = results["distances"][0]

    # Relaxed threshold — catch more relevant chunks
    filtered_chunks = []
    for chunk, score in zip(chunks, scores):
        if score < 1.6:
            filtered_chunks.append(chunk)

    # Always return at least 5 chunks no matter what
    if len(filtered_chunks) < 5:
        return chunks[:5]

    return filtered_chunks