"""OCI configuration management."""

from typing import Optional
from app.db.crud import get_oci_config_by_user_id
from app.utils.encryption import decrypt_private_key


def get_oci_config(user_id: int) -> Optional[dict]:
    """Get OCI configuration for a user from database.
    
    Returns a dict with OCI config values, or None if not found.
    The private key is decrypted when retrieved from the database.
    """
    config = get_oci_config_by_user_id(user_id)
    if not config:
        return None
    
    # Decrypt the private key
    decrypted_key = decrypt_private_key(config["private_key_encrypted"])
    
    return {
        "tenancy": config["tenancy_ocid"],
        "user": config["user_ocid"],
        "fingerprint": config["fingerprint"],
        "key_file": None,  # We store private_key directly, not file path
        "private_key": decrypted_key,
        "region": config["region"],
    }


def get_oci_config_dict(user_id: int) -> Optional[dict]:
    """Get OCI configuration as a dict for OCI SDK initialization.
    
    Returns a dict compatible with oci.config.from_dict() or None if not found.
    """
    config = get_oci_config(user_id)
    if not config:
        return None
    
    # Format for OCI SDK
    return {
        "tenancy": config["tenancy"],
        "user": config["user"],
        "fingerprint": config["fingerprint"],
        "key_content": config["private_key"],
        "region": config["region"],
    }

