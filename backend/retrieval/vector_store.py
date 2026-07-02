import os
import logging
import re
from typing import List, Dict, Any
import chromadb
from backend.config import settings

logger = logging.getLogger("loom.vector_store")

_client = None

def get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        path = settings.vector_store_path
        os.makedirs(path, exist_ok=True)
        _client = chromadb.PersistentClient(path=path)
    return _client

def get_collection_name(collection_name: str) -> str:
    """Sanitizes collection name and adds provider suffix to isolate dimensions."""
    provider = settings.embedding_provider.lower()
    suffix = f"_{provider}"
    clean = collection_name.lower().replace(".", "_").replace("/", "_").replace("-", "_")
    if not clean.endswith(suffix):
        return f"{clean}{suffix}"
    return clean

def init_collection(collection_name: str) -> chromadb.Collection:
    client = get_chroma_client()
    clean_name = get_collection_name(collection_name)
    return client.get_or_create_collection(name=clean_name)

def delete_collection(collection_name: str):
    client = get_chroma_client()
    clean_name = get_collection_name(collection_name)
    try:
        client.delete_collection(name=clean_name)
        logger.info(f"Deleted collection '{clean_name}'")
    except Exception as e:
        logger.warning(f"Failed to delete collection '{clean_name}': {e}")

def upsert_chunks(collection_name: str, chunks: List[Dict[str, Any]], embeddings: List[List[float]]):
    if not chunks:
        return

    collection = init_collection(collection_name)
    
    ids = []
    metadatas = []
    documents = []
    filtered_embeddings = []
    
    seen_ids = set()
    
    for i, chunk in enumerate(chunks):
        file_path = chunk["file"]
        l_start = chunk["line_start"]
        l_end = chunk["line_end"]
        chunk_id = f"{file_path}:{l_start}:{l_end}"
        
        if chunk_id in seen_ids:
            continue
            
        seen_ids.add(chunk_id)
        ids.append(chunk_id)
        documents.append(chunk["code"])
        metadatas.append({
            "file": file_path,
            "function_name": chunk["function_name"] or "",
            "line_start": int(l_start),
            "line_end": int(l_end),
            "file_hash": chunk.get("file_hash") or ""
        })
        if embeddings and i < len(embeddings):
            filtered_embeddings.append(embeddings[i])

    if not ids:
        return

    collection.upsert(
        ids=ids,
        embeddings=filtered_embeddings if filtered_embeddings else None,
        metadatas=metadatas,
        documents=documents
    )
    logger.info(f"Successfully upserted {len(ids)} unique chunks into collection '{collection_name}'")

def query_collection(
    collection_name: str,
    query_embedding: List[float],
    top_k: int = 8,
    where_file: str = None
) -> List[Dict[str, Any]]:
    client = get_chroma_client()
    clean_name = get_collection_name(collection_name)
    
    try:
        collection = client.get_collection(name=clean_name)
    except Exception:
        logger.warning(f"Collection '{clean_name}' not found.")
        return []

    query_args = {
        "query_embeddings": [query_embedding],
        "n_results": top_k
    }
    if where_file:
        query_args["where"] = {"file": where_file}

    results = collection.query(**query_args)

    chunks = []
    if not results or not results["ids"] or not results["ids"][0]:
        return chunks

    ids = results["ids"][0]
    distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)
    metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
    documents = results["documents"][0] if results.get("documents") else [""] * len(ids)

    for i in range(len(ids)):
        meta = metadatas[i]
        dist = distances[i]
        score = 1.0 / (1.0 + dist)
        
        chunks.append({
            "file": meta.get("file", ""),
            "function_name": meta.get("function_name") or None,
            "code": documents[i],
            "line_start": meta.get("line_start", 1),
            "line_end": meta.get("line_end", 1),
            "score": score,
            "relation": "similar"
        })

    return chunks

def get_all_chunks(collection_name: str) -> List[Dict[str, Any]]:
    client = get_chroma_client()
    clean_name = get_collection_name(collection_name)
    try:
        collection = client.get_collection(name=clean_name)
    except Exception:
        return []
        
    res = collection.get(include=["documents", "metadatas"])
    
    chunks_list = []
    if not res or not res.get("documents"):
        return []
        
    documents = res["documents"]
    metadatas = res["metadatas"]
    
    for i in range(len(documents)):
        meta = metadatas[i]
        chunks_list.append({
            "file": meta.get("file", ""),
            "function_name": meta.get("function_name") or None,
            "code": documents[i],
            "line_start": meta.get("line_start", 1),
            "line_end": meta.get("line_end", 1),
            "file_hash": meta.get("file_hash", "")
        })
        
    return chunks_list

def delete_chunks(collection_name: str, ids: List[str]):
    if not ids:
        return
    client = get_chroma_client()
    clean_name = get_collection_name(collection_name)
    try:
        collection = client.get_collection(name=clean_name)
        collection.delete(ids=ids)
        logger.info(f"Deleted {len(ids)} chunks from collection '{clean_name}'")
    except Exception as e:
        logger.warning(f"Failed to delete chunks from collection '{clean_name}': {e}")

def get_collection_metadata(collection_name: str) -> Dict[str, Any]:
    client = get_chroma_client()
    clean_name = get_collection_name(collection_name)
    try:
        collection = client.get_collection(name=clean_name)
        return collection.get(include=["metadatas"])
    except Exception:
        return {"ids": [], "metadatas": []}
