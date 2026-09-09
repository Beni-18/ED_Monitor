import chromadb
from chromadb.utils import embedding_functions
from dataset import CLINICAL_GUIDELINES
import os

DB_PATH = "/Users/bennish/Documents/COE-PROJECT/backend/chroma_db"
COLLECTION_NAME = "clinical_guidelines"

def get_client():
    return chromadb.PersistentClient(path=DB_PATH)

def initialize_vector_store():
    client = get_client()
    # Use default sentence-transformers embedding function
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    
    # Try to get or create collection
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=emb_fn
    )
    
    # Check if empty
    if collection.count() == 0:
        documents = CLINICAL_GUIDELINES
        ids = [f"doc_{i}" for i in range(len(documents))]
        collection.add(
            documents=documents,
            ids=ids
        )
        print("Vector store initialized with clinical guidelines.")
    else:
        print("Vector store already initialized.")

def retrieve_similar_cases(query: str, n_results: int = 3) -> list[str]:
    client = get_client()
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_collection(name=COLLECTION_NAME, embedding_function=emb_fn)
    
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    if results['documents'] and len(results['documents']) > 0:
        return results['documents'][0]
    return []
