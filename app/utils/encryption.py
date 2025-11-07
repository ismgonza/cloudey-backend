"""Encryption utilities for sensitive data."""

import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64


def get_encryption_key() -> bytes:
    """Get encryption key from environment variable.
    
    Returns bytes that Fernet can use directly (base64-encoded key as bytes).
    
    If OCI_ENCRYPTION_KEY is set, use it directly (must be base64-encoded Fernet key string).
    Otherwise, derive from OCI_ENCRYPTION_PASSWORD if set.
    """
    # Option 1: Direct Fernet key from env (base64-encoded string)
    encryption_key = os.getenv("OCI_ENCRYPTION_KEY")
    if encryption_key:
        encryption_key = encryption_key.strip()
        try:
            # Validate it's valid base64 and correct length when decoded
            decoded = base64.urlsafe_b64decode(encryption_key.encode())
            if len(decoded) != 32:
                raise ValueError(
                    f"OCI_ENCRYPTION_KEY must be 32 bytes when decoded. "
                    f"Generate a new key with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
            # Fernet expects the base64-encoded key as bytes, not decoded bytes
            return encryption_key.encode()
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(
                f"OCI_ENCRYPTION_KEY must be a valid base64-encoded Fernet key. "
                f"Error: {str(e)}. "
                f"Generate a new key with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
    
    # Option 2: Derive key from password
    password = os.getenv("OCI_ENCRYPTION_PASSWORD")
    if password:
        # Derive a key from the password using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'cloudey_oci_salt',  # Fixed salt - in production, consider storing per-user salt
            iterations=100000,
            backend=default_backend()
        )
        # Return as base64-encoded bytes for Fernet
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))
    
    raise ValueError(
        "Either OCI_ENCRYPTION_KEY or OCI_ENCRYPTION_PASSWORD must be set in .env. "
        "Generate a key with: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )


def get_cipher() -> Fernet:
    """Get Fernet cipher instance for encryption/decryption."""
    key = get_encryption_key()
    return Fernet(key)


def encrypt_private_key(private_key: str) -> str:
    """Encrypt a private key string.
    
    Args:
        private_key: The private key content as a string
    
    Returns:
        Base64-encoded encrypted string
    """
    cipher = get_cipher()
    encrypted = cipher.encrypt(private_key.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_private_key(encrypted_key: str) -> str:
    """Decrypt a private key string.
    
    Args:
        encrypted_key: Base64-encoded encrypted key string
    
    Returns:
        Decrypted private key content as a string
    """
    cipher = get_cipher()
    encrypted_bytes = base64.urlsafe_b64decode(encrypted_key.encode())
    decrypted = cipher.decrypt(encrypted_bytes)
    return decrypted.decode()

