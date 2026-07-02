import logging
from cryptography.fernet import Fernet
from backend.config import settings

logger = logging.getLogger("loom.security.encryption")

_fernet_key = settings.encryption_key
if not _fernet_key:
    logger.warning(
        "ENCRYPTION_KEY environment variable is not set! "
        "Generating a temporary, transient encryption key for development. "
        "Tokens will not persist securely across restarts."
    )
    _fernet_key = Fernet.generate_key().decode()

try:
    _cipher = Fernet(_fernet_key.encode())
except Exception as e:
    logger.error(f"Failed to initialize Fernet cipher. Ensure ENCRYPTION_KEY is a valid base64 key: {e}")
    raise

def encrypt_token(token: str) -> str:
    """Encrypts a plaintext string (e.g. access token) using Fernet."""
    if not token:
        return ""
    return _cipher.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypts a Fernet-encrypted string back to plaintext."""
    if not encrypted_token:
        return ""
    return _cipher.decrypt(encrypted_token.encode()).decode()
