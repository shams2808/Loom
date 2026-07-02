import uuid
from typing import Optional
from pydantic import BaseModel

class IndexingProgress(BaseModel):
    repo_id: str
    repo_full_name: str
    status: str
    current_batch: int = 0
    total_batches: int = 0
    files_processed: int = 0
    total_chunks: int = 0
    error: Optional[str] = None

# Global in-memory dictionary tracking active indexing jobs
indexing_jobs = {}
