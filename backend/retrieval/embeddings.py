import os
import logging
from typing import List
from backend.config import settings

logger = logging.getLogger("loom.embeddings")

class EmbeddingClient:
    def __init__(self):
        self.provider = settings.embedding_provider.lower()
        self.model = settings.embedding_model

        if self.provider == "local":
            logger.info("Initializing local ONNX embedding client (all-MiniLM-L6-v2)...")
            from chromadb.utils import embedding_functions
            self.client = embedding_functions.ONNXMiniLM_L6_V2()
            
            # Intercept SessionOptions to limit CPU thread utilization and prevent overheating
            try:
                original_session_options = self.client.ort.SessionOptions
                
                def custom_session_options(*args, **kwargs):
                    so = original_session_options(*args, **kwargs)
                    so.intra_op_num_threads = 2
                    so.inter_op_num_threads = 2
                    return so
                    
                self.client.ort.SessionOptions = custom_session_options
                logger.info("Successfully configured local ONNX client to limit execution to 2 CPU threads.")
            except Exception as thread_err:
                logger.warning(f"Could not configure ONNX session thread limit: {thread_err}")
        elif self.provider == "mock":
            logger.info("Using Mock Embedding Client (for testing)")
        else:
            raise ValueError(f"Unknown embedding provider: {self.provider}")

    def embed(self, text: str) -> List[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        if self.provider == "local":
            return self.client(texts)
        elif self.provider == "mock":
            return [[0.1] * 384 for _ in texts]
        return []

_client = None

def get_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client

def embed(text: str) -> List[float]:
    return get_client().embed(text)

def embed_batch(texts: List[str]) -> List[List[float]]:
    return get_client().embed_batch(texts)
