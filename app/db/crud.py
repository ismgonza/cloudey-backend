import psycopg2
from app.db.database import get_db_connection
from app.utils.encryption import encrypt_private_key


def create_user(email: str) -> int:
    """Create a new user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("INSERT INTO users (email) VALUES (%s) RETURNING id", (email,))
        user_id = cursor.fetchone()['id']
        conn.commit()
        return user_id
    except psycopg2.IntegrityError:
        raise ValueError(f"User with email {email} already exists")
    finally:
        conn.close()


def get_user_by_email(email: str):
    """Get user by email."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def get_user_by_id(user_id: int):
    """Get user by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def create_or_update_oci_config(
    user_id: int,
    tenancy_ocid: str,
    user_ocid: str,
    fingerprint: str,
    private_key: str,
    region: str
) -> int:
    """Create or update OCI configuration for a user.
    
    The private key is encrypted before storing in the database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Encrypt the private key before storing
        encrypted_key = encrypt_private_key(private_key)
        
        # Check if config exists
        cursor.execute("SELECT id FROM oci_configs WHERE user_id = %s", (user_id,))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing config
            cursor.execute("""
                UPDATE oci_configs 
                SET tenancy_ocid = %s, user_ocid = %s, fingerprint = %s, 
                    private_key_encrypted = %s, region = %s, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (tenancy_ocid, user_ocid, fingerprint, encrypted_key, region, user_id))
            conn.commit()
            return existing["id"]
        else:
            # Create new config
            cursor.execute("""
                INSERT INTO oci_configs 
                (user_id, tenancy_ocid, user_ocid, fingerprint, private_key_encrypted, region)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, tenancy_ocid, user_ocid, fingerprint, encrypted_key, region))
            config_id = cursor.fetchone()['id']
            conn.commit()
            return config_id
    finally:
        conn.close()


def get_oci_config_by_user_id(user_id: int):
    """Get OCI configuration for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM oci_configs WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


# ============================================================================
# Session Operations
# ============================================================================

def create_or_update_session(session_id: str, user_id: int, title: str = None) -> int:
    """Create or update a session for a user.
    
    Args:
        session_id: Unique session identifier
        user_id: User ID who owns this session
        title: Optional title for the session (e.g., first message)
    
    Returns:
        Session ID (database primary key)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if session exists
        cursor.execute("SELECT id FROM sessions WHERE session_id = %s", (session_id,))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing session
            cursor.execute("""
                UPDATE sessions 
                SET updated_at = CURRENT_TIMESTAMP, title = COALESCE(%s, title)
                WHERE session_id = %s
            """, (title, session_id))
            conn.commit()
            return existing["id"]
        else:
            # Create new session
            cursor.execute("""
                INSERT INTO sessions (session_id, user_id, title)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (session_id, user_id, title))
            session_db_id = cursor.fetchone()['id']
            conn.commit()
            return session_db_id
    finally:
        conn.close()


def get_sessions_by_user(user_id: int, limit: int = 50):
    """Get all sessions for a user.
    
    Args:
        user_id: User ID
        limit: Maximum number of sessions to return
    
    Returns:
        List of session dictionaries
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, session_id, user_id, title, created_at, updated_at
            FROM sessions
            WHERE user_id = %s
            ORDER BY updated_at DESC
            LIMIT %s
        """, (user_id, limit))
        
        return cursor.fetchall()
    finally:
        conn.close()


def get_session_by_id(session_id: str):
    """Get a session by its session_id.
    
    Args:
        session_id: Session identifier
    
    Returns:
        Session dictionary or None
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, session_id, user_id, title, created_at, updated_at
            FROM sessions
            WHERE session_id = %s
        """, (session_id,))
        
        return cursor.fetchone()
    finally:
        conn.close()


def delete_session(session_id: str):
    """Delete a session.
    
    Args:
        session_id: Session identifier
    
    Returns:
        Number of rows deleted
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

