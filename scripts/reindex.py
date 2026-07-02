import os
import argparse
import sys
import logging
from typing import List

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.retrieval.chunking import chunk_file
from backend.retrieval.embeddings import embed_batch
from backend.retrieval.vector_store import upsert_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reindex")

EXCLUDE_DIRS = {
    "node_modules",
    ".git",
    "build",
    "dist",
    ".next",
    "venv",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "Pods",
    "Carthage",
    "DerivedData"
}

EXCLUDE_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "Gemfile.lock",
    "poetry.lock",
    "mix.lock",
    ".DS_Store"
}

SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".swift", ".html", ".css", ".md", ".json",
    ".sh", ".yml", ".yaml", ".go", ".c", ".cpp", ".h", ".java", ".kt", ".rs"
}

def is_binary(file_path: str) -> bool:
    """Returns True if the file contains binary characters, False otherwise."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            return b"\0" in chunk
    except Exception:
        return True

def index_repository(repo_id: str, path: str):
    """Walks the repository path, chunks supported source files, embeds them, and stores in vector store."""
    if not os.path.exists(path):
        logger.error(f"Provided path '{path}' does not exist.")
        sys.exit(1)

    logger.info(f"Starting indexing for repo '{repo_id}' at path '{path}'...")
    
    all_chunks = []
    files_processed = 0

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        for file in files:
            if file in EXCLUDE_FILES:
                continue
                
            _, ext = os.path.splitext(file.lower())
            if ext not in SUPPORTED_EXTENSIONS:
                continue
                
            full_path = os.path.join(root, file)
            if is_binary(full_path):
                continue

            rel_path = os.path.relpath(full_path, path)

            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                
                file_chunks = chunk_file(rel_path, content)
                all_chunks.extend(file_chunks)
                files_processed += 1
            except Exception as e:
                logger.error(f"Failed to process file '{rel_path}': {e}")
                sys.exit(1)

    logger.info(f"Found {files_processed} files yielding {len(all_chunks)} chunks.")
    
    if not all_chunks:
        logger.warning("No chunks created. Vector store will not be updated.")
        return

    # Dynamic batching
    batches = []
    current_batch = []
    current_char_count = 0
    max_chars_per_batch = 20000

    for chunk in all_chunks:
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
    logger.info(f"Split {len(all_chunks)} chunks into {total_batches} batches.")

    for idx, batch in enumerate(batches):
        batch_texts = [c["code"] for c in batch]
        
        try:
            logger.info(f"Processing batch {idx + 1} of {total_batches} ({len(batch)} chunks)...")
            batch_embeddings = embed_batch(batch_texts)
            upsert_chunks(repo_id, batch, batch_embeddings)
        except Exception as e:
            logger.error(f"Failed embedding/upserting batch {idx + 1}: {e}")
            sys.exit(1)

    logger.info(f"Indexing complete! Scoped under repo ID: '{repo_id}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index a repository into the Loom vector store.")
    parser.add_argument("--repo", required=True, help="Unique identifier for the repository (e.g. 'skope')")
    parser.add_argument("--path", required=True, help="Absolute or relative path to the local repository directory")
    args = parser.parse_args()

    index_repository(args.repo, args.path)
