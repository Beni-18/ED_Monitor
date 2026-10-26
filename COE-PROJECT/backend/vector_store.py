import chromadb
from chromadb.utils import embedding_functions
from dataset import CLINICAL_GUIDELINES
import os
import threading

# Resolve path relative to this file so it works on any machine and in Docker
DB_PATH = os.environ.get("CHROMA_DB_PATH", os.path.join(os.path.dirname(__file__), "chroma_db"))
COLLECTION_NAME = "clinical_guidelines"

# The client, embedding model and collection are expensive to build, so share one
# of each across threads (batch evaluation queries concurrently).
_lock = threading.Lock()
_client = None
_emb_fn = None
_collection = None


def get_client():
    global _client
    with _lock:
        if _client is None:
            _client = chromadb.PersistentClient(path=DB_PATH)
        return _client


def _get_emb_fn():
    global _emb_fn
    with _lock:
        if _emb_fn is None:
            _emb_fn = embedding_functions.DefaultEmbeddingFunction()
        return _emb_fn


def _get_collection():
    global _collection
    if _collection is None:
        client, emb_fn = get_client(), _get_emb_fn()
        with _lock:
            if _collection is None:
                _collection = client.get_collection(name=COLLECTION_NAME, embedding_function=emb_fn)
    return _collection

def initialize_vector_store():
    global _collection
    client = get_client()
    emb_fn = _get_emb_fn()
    _collection = None  # force re-fetch after any rebuild below

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
    collection = _get_collection()
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    if results['documents'] and len(results['documents']) > 0:
        return results['documents'][0]
    return []
