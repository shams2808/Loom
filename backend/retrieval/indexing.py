import os
import asyncio
import shutil
import logging
import subprocess
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.future import select

from backend.config import settings
from backend.db.base import AsyncSessionLocal
from backend.db.models import IndexedRepo
from backend.db import crud
from backend.retrieval.chunking import chunk_file
from backend.retrieval.embeddings import embed_batch
from backend.retrieval.vector_store import upsert_chunks, delete_chunks, get_collection_metadata
from backend.session.indexing_status import indexing_jobs, IndexingProgress

logger = logging.getLogger("loom.retrieval.indexing")

EXCLUDE_DIRS = {
    "node_modules", ".git", "build", "dist", ".next", "venv", ".venv",
    "__pycache__", "target", "out", ".idea", ".vscode", "temp_clones"
}

EXCLUDE_FILES = {
    "Cargo.lock", ".DS_Store", "LICENSE", "README.md",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Gemfile.lock",
    "composer.lock", "go.sum", "go.mod"
}

VALID_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".swift", ".java", ".cpp",
    ".h", ".c", ".go", ".rs", ".rb", ".php", ".pyi"
}

def get_file_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()

async def index_repository_pipeline(
    user_id: uuid.UUID,
    repo_db_id: uuid.UUID,
    repo_full_name: str,
    access_token: str,
    collection_name: str,
    custom_clone_url: Optional[str] = None
):
    """
    Clones the user repository using their access token, runs chunking and embedding,
    upserts into the Chroma collection, and updates status in the SQLite DB.
    """
    repo_id_str = str(repo_db_id)
    
    # 1. Initialize progress state
    indexing_jobs[repo_id_str] = IndexingProgress(
        repo_id=repo_id_str,
        repo_full_name=repo_full_name,
        status="indexing",
        current_batch=0,
        total_batches=0,
        files_processed=0,
        total_chunks=0
    )
    
    # Create temp clone directory outside the workspace to prevent Uvicorn reloading
    import tempfile
    temp_repo_path = os.path.join(tempfile.gettempdir(), "loom_clones", repo_id_str)
    os.makedirs(os.path.dirname(temp_repo_path), exist_ok=True)
    
    if os.path.exists(temp_repo_path):
        shutil.rmtree(temp_repo_path, ignore_errors=True)

    db_status = "ready"
    total_chunks_indexed = 0
    error_message = None
    current_sha = None

    try:
        # 2. Get existing metadata for caching
        logger.info(f"Retrieving existing metadata from collection '{collection_name}' for incremental indexing...")
        existing_data = get_collection_metadata(collection_name)
        existing_ids = existing_data.get("ids") or []
        existing_metadatas = existing_data.get("metadatas") or []
        
        # Build cache map: file_path -> {"file_hash": file_hash, "ids": [id1, id2, ...]}
        existing_files_cache = {}
        for chunk_id, meta in zip(existing_ids, existing_metadatas):
            if not meta:
                continue
            f_path = meta.get("file")
            f_hash = meta.get("file_hash")
            if f_path:
                if f_path not in existing_files_cache:
                    existing_files_cache[f_path] = {"file_hash": f_hash, "ids": []}
                existing_files_cache[f_path]["ids"].append(chunk_id)

        # 3. Clone the repository asynchronously
        if custom_clone_url:
            clone_url = custom_clone_url
        else:
            clone_url = f"https://{access_token}@github.com/{repo_full_name}.git"
        logger.info(f"Cloning {repo_full_name} into {temp_repo_path}...")
        
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "clone", "--depth", "1", clone_url, temp_repo_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )
        
        if result.returncode != 0:
            clean_err = result.stderr.replace(access_token, "********")
            raise RuntimeError(f"Git clone failed: {clean_err}")

        # Get latest commit SHA
        sha_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "HEAD"],
            cwd=temp_repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if sha_result.returncode == 0:
            current_sha = sha_result.stdout.strip()
            logger.info(f"Cloned repository at commit SHA: {current_sha}")
        else:
            logger.warning(f"Failed to get commit SHA: {sha_result.stderr.strip()}")

        # 4. Traverse cloned files
        chunks_to_embed = []
        retained_ids = []
        files_count = 0
        cache_hits = 0
        
        for root, dirs, files in os.walk(temp_repo_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            
            for file in files:
                # Check for mid-indexing cancellation
                if repo_id_str not in indexing_jobs or indexing_jobs[repo_id_str].status in ("failed", "cancelled"):
                    raise RuntimeError("Indexing cancelled by user")

                if file in EXCLUDE_FILES:
                    continue
                
                _, ext = os.path.splitext(file.lower())
                if ext not in VALID_EXTENSIONS:
                    continue
                
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, temp_repo_path)
                
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    
                    files_count += 1
                    f_hash = get_file_hash(content)
                    
                    cached = existing_files_cache.get(rel_path)
                    if cached and cached.get("file_hash") == f_hash:
                        retained_ids.extend(cached["ids"])
                        cache_hits += 1
                    else:
                        file_chunks = chunk_file(rel_path, content)
                        file_chunks = [c for c in file_chunks if c["code"] and c["code"].strip()]
                        for chunk in file_chunks:
                            chunk["file_hash"] = f_hash
                            chunks_to_embed.append(chunk)
                except Exception as file_err:
                    logger.warning(f"Failed parsing file {rel_path}: {file_err}")

        logger.info(
            f"Parsed {files_count} files. Cache hits: {cache_hits}. "
            f"Retained {len(retained_ids)} chunks. Queueing {len(chunks_to_embed)} chunks for embedding."
        )
        indexing_jobs[repo_id_str].files_processed = files_count
        
        # 5. Delete outdated chunks
        ids_to_delete = list(set(existing_ids) - set(retained_ids))
        if ids_to_delete:
            logger.info(f"Deleting {len(ids_to_delete)} outdated chunks from collection...")
            await asyncio.to_thread(delete_chunks, collection_name, ids_to_delete)
        
        total_chunks_indexed = len(retained_ids)
        
        if not chunks_to_embed:
            logger.info("All files are up to date. No new embeddings needed.")
            db_status = "ready"
        else:
            # 6. Dynamic batching
            batches = []
            current_batch = []
            current_char_count = 0
            max_chars_per_batch = 20000

            for chunk in chunks_to_embed:
                chunk_len = len(chunk["code"])
                if current_batch and current_char_count + chunk_len > max_chars_per_batch:
                    batches.append(current_batch)
                    current_batch = [chunk]
                    current_char_count = chunk_len
                else:
                    current_batch.append(chunk)
                    current_char_count += chunk_len

            if current_batch:
                batches.append(current_batch)

            total_batches = len(batches)
            indexing_jobs[repo_id_str].total_batches = total_batches
            logger.info(f"Split {len(chunks_to_embed)} chunks into {total_batches} batches.")

            # 7. Process batches
            for idx, batch in enumerate(batches):
                if repo_id_str not in indexing_jobs or indexing_jobs[repo_id_str].status in ("failed", "cancelled"):
                    raise RuntimeError("Indexing cancelled by user")

                batch_texts = [c["code"] for c in batch]
                batch_embeddings = await asyncio.to_thread(embed_batch, batch_texts)

                # Upsert into Chroma
                await asyncio.to_thread(upsert_chunks, collection_name, batch, batch_embeddings)
                
                total_chunks_indexed += len(batch)
                indexing_jobs[repo_id_str].current_batch = idx + 1
                indexing_jobs[repo_id_str].total_chunks = total_chunks_indexed

    except Exception as pipeline_err:
        logger.exception(f"Repository indexing failed: {pipeline_err}")
        db_status = "failed"
        error_message = str(pipeline_err)
        indexing_jobs[repo_id_str].status = "failed"
        indexing_jobs[repo_id_str].error = error_message
    
    finally:
        logger.info(f"Cleaning up directory {temp_repo_path}...")
        shutil.rmtree(temp_repo_path, ignore_errors=True)

    # 8. Update DB status
    async with AsyncSessionLocal() as db:
        try:
            await crud.update_repo_status(
                db=db,
                repo_db_id=repo_db_id,
                status=db_status,
                chunk_count=total_chunks_indexed,
                last_commit_sha=current_sha if db_status == "ready" else None,
                last_indexed_at=datetime.now(timezone.utc)
            )
            logger.info(f"Database status updated to '{db_status}' for repo ID {repo_db_id}.")
        except Exception as db_err:
            logger.error(f"Failed to update database repository indexing status: {db_err}")

    if db_status == "ready":
        indexing_jobs[repo_id_str].status = "completed"
