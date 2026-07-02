import re
import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from backend.db import crud
from backend.db.base import AsyncSessionLocal
from backend.retrieval.embeddings import embed
from backend.retrieval.vector_store import query_collection, get_all_chunks

logger = logging.getLogger("loom.retrieval.interface")

class ContextChunk(BaseModel):
    file: str = Field(..., description="File path relative to repository root")
    function_name: Optional[str] = Field(None, description="Function or class name if identified")
    code: str = Field(..., description="The code content of this chunk")
    line_start: int = Field(..., description="Starting line number in the source file")
    line_end: int = Field(..., description="Ending line number in the source file")
    score: float = Field(..., description="Vector search similarity score (0 to 1)")
    relation: Optional[str] = Field(None, description="'similar' | 'caller' | None")

def extract_function_name(diff_chunk: str) -> Optional[str]:
    """
    Extracts the name of the function/method being changed from a diff chunk.
    Scans modified lines first, then context lines.
    """
    lines = diff_chunk.splitlines()
    
    patterns = [
        # Python: def foo(...)
        re.compile(r'def\s+([a-zA-Z0-9_]+)'),
        # JS/TS: function foo(...)
        re.compile(r'function\s*\*?\s*([a-zA-Z0-9_$]+)'),
        # JS/TS Arrow: const foo = (...) =>
        re.compile(r'(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>'),
        # Swift: func foo(...)
        re.compile(r'func\s+([a-zA-Z0-9_]+)'),
        # JS/TS Class Method: myMethod(...) {
        re.compile(r'^[ \t]*(?:async\s+)?(?:get\s+|set\s+)?\*?\s*([a-zA-Z0-9_$]+)\s*\([^)]*\)\s*\{?', re.M)
    ]
    
    ignored_keywords = {"if", "for", "while", "switch", "catch", "function", "def", "func", "class", "struct", "let", "const", "var"}

    # 1. Prioritize modified lines (additions/deletions)
    for line in lines:
        if line.startswith('+') or line.startswith('-'):
            stripped = line[1:].strip()
            for pat in patterns:
                m = pat.search(stripped)
                if m:
                    name = m.group(1)
                    if name not in ignored_keywords:
                        return name
                        
    # 2. Fallback to any line in the chunk
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('+') or stripped.startswith('-'):
            stripped = stripped[1:].strip()
        for pat in patterns:
            m = pat.search(stripped)
            if m:
                name = m.group(1)
                if name not in ignored_keywords:
                    return name
                    
    return None

async def retrieve_context(
    query: str,
    repo_id: str,           # The database UUID of the repo (or vector collection name if already resolved)
    user_id: str,           # Used to look up the repository and scope Chroma collection name
    top_k: int = 8,
    include_callers: bool = True,
    current_file: Optional[str] = None
) -> List[ContextChunk]:
    """
    Retrieves relevant code context (similar code and caller sites) for a query/diff chunk.
    Scopes retrieval to the user's private collection.
    """
    if not query.strip():
        return []

    # 1. Resolve vector collection name from SQLite database
    import uuid
    collection_name = repo_id
    try:
        repo_uuid = uuid.UUID(repo_id)
        user_uuid = uuid.UUID(user_id)
        async with AsyncSessionLocal() as db:
            repo = await crud.get_indexed_repo_by_id(db, user_uuid, repo_uuid)
            if repo:
                collection_name = repo.vector_collection_name
            else:
                logger.warning(f"Repository {repo_id} not found for user {user_id}. Retrieval aborted.")
                return []
    except ValueError:
        # If repo_id or user_id are not UUIDs, use repo_id as collection name directly (e.g. in tests/CLI)
        pass

    # 2. Query similarity from vector store
    query_embedding = embed(query)
    similar_results = []
    
    # Scope query in active file first if provided
    if current_file:
        try:
            active_file_results = query_collection(collection_name, query_embedding, top_k=4, where_file=current_file)
            similar_results.extend(active_file_results)
        except Exception as e:
            logger.warning(f"Failed to query active file {current_file}: {e}")

    general_results = query_collection(collection_name, query_embedding, top_k=top_k)
    similar_results.extend(general_results)

    # 3. Caller site detection (Cassandra logic)
    caller_results = []
    if include_callers:
        changed_func_name = extract_function_name(query)
        if changed_func_name:
            all_chunks = get_all_chunks(collection_name)
            call_site_pattern = re.compile(r'\b' + re.escape(changed_func_name) + r'\b')
            
            for chunk in all_chunks:
                # Skip if this chunk is the function definition itself
                if chunk["function_name"] == changed_func_name:
                    continue
                if call_site_pattern.search(chunk["code"]):
                    caller_results.append({
                        "file": chunk["file"],
                        "function_name": chunk["function_name"],
                        "code": chunk["code"],
                        "line_start": chunk["line_start"],
                        "line_end": chunk["line_end"],
                        "score": 0.0,
                        "relation": "caller"
                    })

    # 4. Merge results and deduplicate by (file, code)
    seen = set()
    merged = []
    
    # Add similarity results first
    for res in similar_results:
        key = (res["file"], res["code"].strip())
        seen.add(key)
        
        # In Q&A mode relation is None, otherwise "similar"
        relation = "similar" if include_callers else None
        merged.append(ContextChunk(
            file=res["file"],
            function_name=res["function_name"],
            code=res["code"],
            line_start=res["line_start"],
            line_end=res["line_end"],
            score=res["score"],
            relation=relation
        ))
        
    # Add caller results if they aren't already included
    for res in caller_results:
        key = (res["file"], res["code"].strip())
        if key not in seen:
            seen.add(key)
            merged.append(ContextChunk(
                file=res["file"],
                function_name=res["function_name"],
                code=res["code"],
                line_start=res["line_start"],
                line_end=res["line_end"],
                score=res["score"],
                relation=res["relation"]
            ))

    return merged
