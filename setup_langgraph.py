"""
Setup script to initialize LangGraph checkpoint tables.
Run this once before starting the application.
"""
import asyncio
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.sysconfig import DatabaseConfig


async def setup_langgraph_tables():
    """Setup LangGraph checkpoint tables."""
    print("🔧 Setting up LangGraph checkpoint tables...")
    
    # Create async connection pool with autocommit for CREATE INDEX CONCURRENTLY
    pool = AsyncConnectionPool(
        conninfo=DatabaseConfig.DATABASE_URL,
        min_size=1,
        max_size=2,
        open=False,
        kwargs={"autocommit": True}  # Required for CREATE INDEX CONCURRENTLY
    )
    
    try:
        # Open the pool
        await pool.open()
        print("✅ Connected to database")
        
        # Create checkpointer and setup tables
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        
        print("✅ LangGraph checkpoint tables created successfully!")
        print("   - checkpoints")
        print("   - checkpoint_blobs")
        print("   - checkpoint_writes")
        
    except Exception as e:
        print(f"❌ Error setting up tables: {e}")
        raise
    finally:
        await pool.close()
        print("✅ Connection pool closed")


if __name__ == "__main__":
    asyncio.run(setup_langgraph_tables())

