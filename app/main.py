import asyncio
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.logging_config import setup_logging
from app.agents import query_agent, get_checkpointer
from app.db.crud import create_user, get_user_by_email, create_or_update_oci_config
from app.dashboard import get_dashboard_data
from app.detailed_costs import get_detailed_costs
from app.recommendations_engine import generate_ai_recommendations
from app.cache import get_cache, get_cost_cache
from app.scheduler import start_scheduler, stop_scheduler, get_scheduler_status
from app.cloud.oci.resource_sync import sync_user_resources
from app.db.resource_crud import get_sync_stats
from app.demo_middleware import DemoModeMiddleware, DEMO_MODE

# Setup logging with DEBUG level
setup_logging(level="DEBUG")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup and cleanup on shutdown."""
    logger.info("=" * 80)
    logger.info("🚀 STARTING CLOUDEY BACKEND APPLICATION")
    logger.info("=" * 80)
    
    # Initialize the checkpointer (creates PostgreSQL tables if needed)
    logger.info("📊 Initializing conversation checkpointer...")
    await get_checkpointer()
    logger.info("✅ Checkpointer initialized (PostgreSQL)")
    
    # DISABLED: Background scheduler (use manual sync button instead)
    # logger.info("⏰ Starting background resource sync scheduler...")
    # start_scheduler()
    # logger.info("✅ Scheduler started (syncs on startup + every 12 hours)")
    
    logger.info("🎯 Application ready to accept requests!")
    logger.info("💡 TIP: Use 'Sync Resources' button in dashboard for manual sync")
    logger.info("=" * 80)
    yield
    
    logger.info("👋 Shutting down Cloudey backend...")
    
    # DISABLED: Stop background scheduler
    # logger.info("⏰ Stopping background scheduler...")
    # stop_scheduler()
    # logger.info("✅ Scheduler stopped")


app = FastAPI(title="Cloudey.app API", version="0.1.0", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Demo Mode Middleware (anonymizes ALL responses when DEMO_MODE=true)
app.add_middleware(DemoModeMiddleware)
if DEMO_MODE:
    logger.warning("=" * 80)
    logger.warning("🎭 DEMO MODE ACTIVE - All API responses will be anonymized!")
    logger.warning("=" * 80)


class QueryRequest(BaseModel):
    question: str
    model_provider: str = "openai"  # "openai" or "anthropic"
    user_id: int = 1  # TODO: Get from auth/session in production
    session_id: str = None  # Optional: for conversation continuity


class QueryResponse(BaseModel):
    answer: str


class OCIConfigRequest(BaseModel):
    email: str
    tenancy_ocid: str
    user_ocid: str
    fingerprint: str
    region: str


class OCIConfigResponse(BaseModel):
    user_id: int
    message: str


class SessionInfo(BaseModel):
    id: int
    session_id: str
    title: str | None
    created_at: str
    updated_at: str


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Query the AI agent with a cloud cost question.
    
    To maintain conversation context across multiple queries, provide the same
    session_id for all queries in the same conversation. If session_id is not
    provided, a default session will be used (no conversation memory across requests).
    """
    start_time = time.time()
    logger.info("=" * 80)
    logger.info(f"📨 NEW QUERY RECEIVED")
    logger.info(f"   User ID: {request.user_id}")
    logger.info(f"   Session: {request.session_id}")
    logger.info(f"   Provider: {request.model_provider}")
    logger.info(f"   Question: {request.question[:100]}...")
    
    # Use session_id if provided, otherwise generate per-user default
    thread_id = request.session_id if request.session_id else f"user_{request.user_id}_default"
    logger.debug(f"📍 Thread ID: {thread_id}")
    
    # Track session in database (links session to user)
    logger.debug("💾 Saving session to database...")
    from app.db.crud import create_or_update_session
    await asyncio.to_thread(
        create_or_update_session,
        thread_id,
        request.user_id,
        request.question[:100] if not request.session_id else None  # Use first question as title for new sessions
    )
    logger.debug("✅ Session saved")
    
    logger.info("🤖 Invoking AI agent...")
    agent_start = time.time()
    answer = await query_agent(
        question=request.question,
        model_provider=request.model_provider,
        user_id=request.user_id,
        thread_id=thread_id
    )
    agent_time = time.time() - agent_start
    
    total_time = time.time() - start_time
    logger.info(f"✅ QUERY COMPLETED")
    logger.info(f"   Agent time: {agent_time:.2f}s")
    logger.info(f"   Total time: {total_time:.2f}s")
    logger.info(f"   Response length: {len(answer)} chars")
    logger.info("=" * 80)
    
    return QueryResponse(answer=answer)


@app.post("/config/oci", response_model=OCIConfigResponse)
async def upload_oci_config(
    email: str = Form(...),
    tenancy_ocid: str = Form(...),
    user_ocid: str = Form(...),
    fingerprint: str = Form(...),
    region: str = Form(...),
    private_key_file: UploadFile = File(...)
):
    """Upload OCI configuration and PEM key file for a user.
    
    Creates or updates OCI config for the user. The PEM file is read and stored securely.
    """
    logger.info("=" * 80)
    logger.info(f"🔑 OCI CONFIG UPLOAD")
    logger.info(f"   Email: {email}")
    logger.info(f"   Region: {region}")
    logger.info(f"   Tenancy: {tenancy_ocid[:20]}...")
    
    # Read PEM file content first
    try:
        logger.debug("📄 Reading PEM file...")
        private_key_content = await private_key_file.read()
        private_key = private_key_content.decode("utf-8")
        logger.debug(f"✅ PEM file read ({len(private_key)} bytes)")
    except Exception as e:
        logger.error(f"❌ Error reading PEM file: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error reading PEM file: {str(e)}")
    
    # Validate PEM format (basic check)
    if not private_key.startswith("-----BEGIN"):
        logger.error("❌ Invalid PEM format")
        raise HTTPException(status_code=400, detail="Invalid PEM file format")
    logger.debug("✅ PEM format validated")
    
    # Run database operations in executor to avoid blocking
    # Get or create user
    try:
        logger.debug(f"🔍 Looking up user by email: {email}")
        user = await asyncio.to_thread(get_user_by_email, email)
        if not user:
            logger.info(f"👤 Creating new user: {email}")
            user_id = await asyncio.to_thread(create_user, email)
            logger.info(f"✅ User created (ID: {user_id})")
        else:
            user_id = user["id"]
            logger.info(f"✅ User found (ID: {user_id})")
    except Exception as e:
        logger.error(f"❌ Error managing user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error managing user: {str(e)}")
    
    # Store OCI config
    try:
        logger.info("💾 Saving encrypted OCI config to database...")
        await asyncio.to_thread(
            create_or_update_oci_config,
            user_id,
            tenancy_ocid,
            user_ocid,
            fingerprint,
            private_key,
            region
        )
        logger.info("✅ OCI config saved successfully")
    except Exception as e:
        logger.error(f"❌ Error saving config: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving config: {str(e)}")
    
    # Start cache warming in background (fire and forget)
    # Temporarily disabled for debugging
    # logger.info("🔥 Starting cache warming...")
    # from app.cloud.oci.cache_warming import warm_user_cache
    # asyncio.create_task(warm_user_cache(user_id))
    
    logger.info(f"✅ OCI CONFIG UPLOAD COMPLETE (User ID: {user_id})")
    logger.info("=" * 80)
    
    return OCIConfigResponse(
        user_id=user_id,
        message="OCI configuration saved successfully"
    )


@app.get("/sessions/{user_id}")
async def get_user_sessions(user_id: int):
    """Get all conversation sessions for a user."""
    from app.db.crud import get_sessions_by_user
    try:
        sessions = await asyncio.to_thread(get_sessions_by_user, user_id)
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching sessions: {str(e)}")


@app.get("/sessions/{user_id}/{session_id}/messages")
async def get_session_messages(user_id: int, session_id: str):
    """Get all messages for a conversation session."""
    from app.agents import get_conversation_history
    try:
        messages = await get_conversation_history(session_id)
        return {"messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching messages: {str(e)}")


@app.delete("/sessions/{session_id}")
async def delete_conversation(session_id: str):
    """Delete a conversation session and its history."""
    from app.db.crud import delete_session
    from app.agents import delete_conversation_history
    try:
        # Delete from sessions table
        await asyncio.to_thread(delete_session, session_id)
        # Delete from checkpoint database
        await delete_conversation_history(session_id)
        return {"message": "Session deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")


@app.get("/cache/stats")
async def get_cache_stats():
    """Get cache statistics."""
    cache = get_cache()
    return cache.get_stats()


@app.delete("/cache/dashboard/{user_id}")
async def clear_dashboard_cache(user_id: int):
    """Clear dashboard cache for a specific user."""
    cache = get_cache()
    deleted = cache.clear_dashboard_cache(user_id)
    return {"message": f"Cleared {deleted} dashboard cache keys for user {user_id}"}


@app.delete("/cache/user/{user_id}")
async def clear_user_cache(user_id: int):
    """Clear all cache for a specific user."""
    cache = get_cache()
    deleted = cache.clear_user_cache(user_id)
    return {"message": f"Cleared {deleted} cache keys for user {user_id}"}


@app.get("/cache/costs/stats/{user_id}")
async def get_cost_cache_stats(user_id: int):
    """
    Get cost cache statistics for a user.
    
    Shows:
    - SQLite: Historical months cached (permanent storage)
    - Redis: Current month cached (temporary in-memory storage)
    
    Returns detailed information about cached cost data across
    both storage tiers of the hybrid caching system.
    """
    logger.info(f"📊 Cost cache stats requested for user {user_id}")
    try:
        cost_cache = get_cost_cache()
        stats = cost_cache.get_stats(user_id)
        return stats
    except Exception as e:
        logger.error(f"Error fetching cost cache stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching cost cache stats: {str(e)}")


@app.get("/dashboard/{user_id}")
async def get_dashboard(user_id: int, force_refresh: bool = False):
    """Get dashboard data for a user.
    
    Args:
        user_id: User ID
        force_refresh: If True, bypass cache and fetch fresh data
    
    Returns comprehensive dashboard data including:
    - Cost overview (total, top compartments, top services)
    - Cost trend (current vs last month)
    - Resource inventory (instances, volumes, etc.)
    - Optimization summary (recommendations and potential savings)
    - Cost alerts
    """
    logger.info(f"📊 Dashboard data requested for user {user_id} (force_refresh={force_refresh})")
    try:
        dashboard_data = await get_dashboard_data(user_id, force_refresh=force_refresh)
        return dashboard_data
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching dashboard data: {str(e)}")


@app.get("/costs/detailed/{user_id}")
async def get_costs_detailed(user_id: int, force_refresh: bool = False):
    """Get detailed cost breakdown for a user.
    
    Args:
        user_id: User ID
        force_refresh: If True, bypass cache and fetch fresh data
    
    Returns detailed cost data including:
    - Compartments with 3-month costs and trends (with expandable services)
    - Services summary across all compartments
    - Top 10 most expensive resources
    - Monthly totals and metadata
    """
    logger.info(f"💰 Detailed costs requested for user {user_id} (force_refresh={force_refresh})")
    try:
        detailed_costs = await get_detailed_costs(user_id, force_refresh=force_refresh)
        return detailed_costs
    except Exception as e:
        logger.error(f"Error fetching detailed costs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching detailed costs: {str(e)}")


@app.get("/recommendations/{user_id}")
async def get_recommendations(user_id: int):
    """
    Get AI-powered cost optimization recommendations for a user.
    
    Uses cached cost data and resource inventory to generate instant insights.
    Provides:
    - Cost trend insights
    - Service optimization recommendations
    - Resource-based savings opportunities
    - Quick wins for immediate savings
    
    Args:
        user_id: User ID
    
    Returns:
        AI-generated recommendations with potential savings estimates
    """
    logger.info(f"🤖 AI recommendations requested for user {user_id}")
    try:
        recommendations = await generate_ai_recommendations(user_id)
        return recommendations
    except Exception as e:
        logger.error(f"Error generating recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


# ===== RESOURCE SYNC ENDPOINTS =====

@app.post("/resources/sync/{user_id}")
async def sync_resources_manual(user_id: int):
    """
    Manually trigger resource sync for a specific user.
    
    Args:
        user_id: User ID
    
    Returns:
        Sync statistics (new, updated, deleted counts)
    """
    logger.info(f"🔄 Manual resource sync requested for user {user_id}")
    try:
        stats = await sync_user_resources(user_id, force=True)
        logger.info(f"✅ Manual sync complete for user {user_id}: {stats}")
        return {
            "message": f"Successfully synced resources for user {user_id}",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"❌ Error syncing resources for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error syncing resources: {str(e)}")


@app.post("/metrics/sync/{user_id}")
async def sync_metrics_manual(user_id: int, days: int = 7):
    """
    Manually trigger metrics sync (utilization data) for a specific user.
    
    Args:
        user_id: User ID
        days: Number of days to look back for metrics (default: 7)
    
    Returns:
        Sync statistics (instances/load balancers checked, metrics saved)
    """
    logger.info(f"📊 Manual metrics sync requested for user {user_id} (last {days} days)")
    try:
        from app.cloud.oci.metrics_sync import sync_all_metrics
        
        stats = await sync_all_metrics(user_id, days)
        
        if stats.get('success'):
            logger.info(f"✅ Metrics sync complete for user {user_id}: {stats['total_metrics_saved']} metrics saved")
            return {
                "message": f"Successfully synced metrics for user {user_id}",
                "stats": stats
            }
        else:
            logger.error(f"❌ Metrics sync failed for user {user_id}: {stats.get('error')}")
            raise HTTPException(status_code=500, detail=f"Metrics sync failed: {stats.get('error')}")
            
    except Exception as e:
        logger.error(f"❌ Error syncing metrics for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error syncing metrics: {str(e)}")


@app.get("/metrics/stats/{user_id}")
async def get_metrics_stats_endpoint(user_id: int):
    """
    Get metrics cache statistics for a user.
    
    Args:
        user_id: User ID
    
    Returns:
        Dictionary with metrics cache stats by resource type
    """
    logger.info(f"📊 Metrics stats requested for user {user_id}")
    try:
        from app.db.metrics_crud import get_metrics_stats
        
        stats = get_metrics_stats(user_id)
        return stats
    except Exception as e:
        logger.error(f"❌ Error getting metrics stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting metrics stats: {str(e)}")


@app.get("/resources/stats/{user_id}")
async def get_resource_stats(user_id: int):
    """
    Get resource sync statistics for a user.
    
    Args:
        user_id: User ID
    
    Returns:
        Dictionary with sync stats (total, active, deleted, last_sync_date)
    """
    logger.info(f"📊 Resource stats requested for user {user_id}")
    try:
        stats = get_sync_stats(user_id)
        return stats
    except Exception as e:
        logger.error(f"❌ Error getting resource stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting resource stats: {str(e)}")


@app.get("/scheduler/status")
async def get_scheduler_status_endpoint():
    """
    Get background scheduler status.
    
    Returns:
        Scheduler status and job information
    """
    logger.info("⏰ Scheduler status requested")
    try:
        status = get_scheduler_status()
        return status
    except Exception as e:
        logger.error(f"❌ Error getting scheduler status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting scheduler status: {str(e)}")

