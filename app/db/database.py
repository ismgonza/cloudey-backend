"""Database connection management for PostgreSQL."""

import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional
import logging

from app.sysconfig import DatabaseConfig

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get PostgreSQL database connection.
    
    Returns connection with RealDictCursor for dict-like row access.
    This maintains compatibility with previous SQLite Row interface.
    """
    try:
        conn = psycopg2.connect(
            DatabaseConfig.DATABASE_URL,
            cursor_factory=RealDictCursor
        )
        return conn
    except psycopg2.Error as e:
        logger.error(f"Database connection failed: {e}")
        raise


def test_connection():
    """Test database connection.
    
    Usage:
        python -m app.db.database
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"✅ Connected to PostgreSQL: {version['version']}")
        
        cursor.execute("SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = 'public';")
        table_count = cursor.fetchone()
        print(f"✅ Database has {table_count['count']} tables")
        
        cursor.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename;")
        tables = cursor.fetchall()
        print(f"\n📊 Tables:")
        for table in tables:
            print(f"   - {table['tablename']}")
        
        conn.close()
        print("\n✅ Database connection test successful!")
        
    except Exception as e:
        print(f"❌ Database connection test failed: {e}")
        raise


if __name__ == "__main__":
    test_connection()

