import chromadb
from chromadb.utils import embedding_functions
from dataset import CLINICAL_GUIDELINES
import os

# Resolve path relative to this file so it works on any machine and in Docker
DB_PATH = os.environ.get("CHROMA_DB_PATH", os.path.join(os.path.dirname(__file__), "chroma_db"))
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

    current_count = collection.count()
    expected_count = len(CLINICAL_GUIDELINES)

    if current_count == 0:
        # Fresh initialization
        documents = CLINICAL_GUIDELINES
        ids = [f"doc_{i}" for i in range(len(documents))]
        collection.add(documents=documents, ids=ids)
        print(f"Vector store initialized with {len(documents)} clinical guidelines.")
    elif current_count != expected_count:
        # Guidelines have changed (e.g. expanded from 15 → 25) — rebuild the store
        print(f"Vector store has {current_count} documents but {expected_count} guidelines defined. Rebuilding...")
        client.delete_collection(COLLECTION_NAME)
        collection = client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=emb_fn)
        documents = CLINICAL_GUIDELINES
        ids = [f"doc_{i}" for i in range(len(documents))]
        collection.add(documents=documents, ids=ids)
        print(f"Vector store rebuilt with {len(documents)} clinical guidelines.")
    else:
        print(f"Vector store already initialized with {current_count} guidelines.")

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
