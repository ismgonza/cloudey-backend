# Cloudey.app Backend 🚀

> **Multi-cloud cost optimization platform powered by AI**
> 
> FastAPI + LangGraph + OCI SDK + PostgreSQL + Redis

---

## 📋 Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Database Setup](#database-setup)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Application Flow](#application-flow)
- [Project Structure](#project-structure)
- [Key Components](#key-components)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

---

## 🎯 Overview

Cloudey.app is an AI-powered cloud cost optimization platform that helps organizations:
- **Track** multi-cloud spending across OCI (AWS coming soon)
- **Analyze** cost trends and identify optimization opportunities
- **Recommend** actionable cost-saving measures with AI
- **Monitor** resource utilization metrics (CPU, Memory, Bandwidth)
- **Chat** with an AI assistant about your cloud infrastructure

### Key Features

✅ **Real-time Cost Tracking** - Syncs with OCI Usage API  
✅ **AI-Powered Recommendations** - LangGraph agents with Claude/GPT  
✅ **Resource Inventory** - Compute, Storage, Databases, Load Balancers  
✅ **Utilization Metrics** - OCI Monitoring integration  
✅ **Smart Caching** - Redis + PostgreSQL for fast queries  
✅ **Conversational AI** - Natural language cost analysis  

---

## 🛠 Tech Stack

### Core Framework
- **FastAPI** `0.104+` - Modern async web framework
- **Uvicorn** - ASGI server with hot reload
- **Python** `3.11+` - Modern Python features

### AI & LLM
- **LangGraph** - Agent orchestration with checkpoints
- **LangChain** - LLM framework (Anthropic Claude, OpenAI GPT)
- **LangGraph Checkpoint Postgres** - Conversation persistence

### Cloud SDKs
- **OCI Python SDK** `2.112+` - Oracle Cloud Infrastructure
- **Boto3** - AWS SDK (future)

### Databases & Caching
- **PostgreSQL** `16` - Primary database (via Docker)
- **Redis** `7.2+` - Cost data caching (via Docker)
- **psycopg2** - PostgreSQL driver

### Task Scheduling
- **APScheduler** - Background jobs (cost rollover, metrics sync)

### Security
- **Cryptography** - Encryption for OCI private keys
- **python-dotenv** - Environment variable management

---

## 🏗 Architecture

### High-Level System Architecture

```mermaid
graph TB
    subgraph "Frontend"
        UI[React UI<br/>Dashboard, Costs, AI Chat]
    end
    
    subgraph "Backend - FastAPI"
        API[API Layer<br/>main.py]
        AGENTS[LangGraph Agents<br/>agents.py]
        RECO[Recommendations Engine<br/>recommendations_engine.py]
        SYNC[Resource Sync<br/>resource_sync.py]
        METRICS[Metrics Sync<br/>metrics_sync.py]
    end
    
    subgraph "Data Layer"
        PG[(PostgreSQL<br/>Resources, Costs, Metrics)]
        REDIS[(Redis<br/>Cost Cache)]
    end
    
    subgraph "External Services"
        OCI[OCI APIs<br/>Usage, Compute, Monitoring]
        LLM[LLM Providers<br/>Claude/GPT]
    end
    
    UI -->|HTTP/REST| API
    API --> AGENTS
    API --> RECO
    API --> SYNC
    API --> METRICS
    
    AGENTS -->|Query| PG
    AGENTS -->|Cache| REDIS
    AGENTS -->|Chat| LLM
    
    RECO -->|Read| PG
    RECO -->|Read| REDIS
    
    SYNC -->|Fetch| OCI
    SYNC -->|Write| PG
    
    METRICS -->|Fetch| OCI
    METRICS -->|Write| PG
    
    style UI fill:#e1f5ff
    style API fill:#fff4e1
    style PG fill:#e8f5e9
    style REDIS fill:#ffebee
    style OCI fill:#f3e5f5
    style LLM fill:#e0f2f1
```

### Data Flow: Cost Tracking

```mermaid
sequenceDiagram
    participant User
    participant API
    participant Redis
    participant PostgreSQL
    participant OCI Usage API
    
    User->>API: GET /costs/detailed
    API->>Redis: Check cache (current month)
    
    alt Cache Hit
        Redis-->>API: Return cached data
        API-->>User: Cost breakdown
    else Cache Miss
        API->>OCI Usage API: Fetch usage data
        OCI Usage API-->>API: Usage records
        API->>Redis: Cache for 1 hour
        API->>PostgreSQL: Store historical data
        API-->>User: Cost breakdown
    end
    
    Note over API,PostgreSQL: Background Job: Monthly Rollover
    PostgreSQL->>Redis: Move current month → PostgreSQL
    PostgreSQL->>Redis: Clear Redis cache
```

### Data Flow: AI Recommendations

```mermaid
graph LR
    subgraph "Input Sources"
        COSTS[Cost Data<br/>PostgreSQL + Redis]
        RESOURCES[Resource Inventory<br/>PostgreSQL]
        METRICS[Utilization Metrics<br/>PostgreSQL]
    end
    
    subgraph "Recommendations Engine"
        ANALYZE[Analyze Costs<br/>Trends, Anomalies]
        CHECK[Check Resources<br/>Stopped, Unattached]
        UTIL[Check Utilization<br/>CPU, Memory, Bandwidth]
        CALC[Calculate Savings<br/>Rightsizing, Reserved]
    end
    
    subgraph "Output"
        RECS[Recommendations<br/>w/ Tables & Actions]
    end
    
    COSTS --> ANALYZE
    RESOURCES --> CHECK
    METRICS --> UTIL
    
    ANALYZE --> CALC
    CHECK --> CALC
    UTIL --> CALC
    
    CALC --> RECS
    
    style COSTS fill:#e8f5e9
    style RESOURCES fill:#e1f5ff
    style METRICS fill:#fff4e1
    style RECS fill:#f3e5f5
```

### Database Schema

```mermaid
erDiagram
    users ||--o{ oci_configs : has
    users ||--o{ oci_compartments : owns
    users ||--o{ oci_compute : owns
    users ||--o{ oci_volumes : owns
    users ||--o{ oci_costs : tracks
    users ||--o{ oci_metrics : monitors
    
    oci_compartments ||--o{ oci_compute : contains
    oci_compartments ||--o{ oci_volumes : contains
    oci_compartments ||--o{ oci_buckets : contains
    oci_compartments ||--o{ oci_load_balancer : contains
    
    oci_compute ||--o{ oci_metrics : has
    oci_load_balancer ||--o{ oci_metrics : has
    
    users {
        int id PK
        string email
        timestamp created_at
    }
    
    oci_configs {
        int id PK
        int user_id FK
        string tenancy
        string user_ocid
        string fingerprint
        text private_key_encrypted
        string region
    }
    
    oci_compartments {
        int id PK
        int user_id FK
        string ocid
        string name
        string lifecycle_state
    }
    
    oci_compute {
        int id PK
        int user_id FK
        string ocid
        string display_name
        string compartment_ocid FK
        string shape
        int vcpus
        int memory_in_gbs
        string lifecycle_state
    }
    
    oci_costs {
        int id PK
        int user_id FK
        string resource_ocid
        string service
        string month
        decimal cost
    }
    
    oci_metrics {
        int id PK
        int user_id FK
        string resource_ocid
        string resource_type
        string metric_name
        decimal metric_value
        timestamp fetched_at
    }
```

---

## ✅ Prerequisites

### Required Software

1. **Python 3.11+**
   ```bash
   python --version  # Should be 3.11 or higher
   ```

2. **Docker & Docker Compose**
   ```bash
   docker --version
   docker-compose --version
   ```

3. **PostgreSQL Client** (optional, for debugging)
   ```bash
   # macOS
   brew install postgresql
   
   # Ubuntu
   apt-get install postgresql-client
   ```

### Required Accounts

- **OCI Account** - Oracle Cloud Infrastructure with API access
- **LLM Provider** - Anthropic Claude or OpenAI GPT API key

---

## 📦 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/ismgonza/cloudey-backend.git
cd cloudey-backend
```

### 2. Install UV (Python Package Manager)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or use pip
pip install uv
```

### 3. Create Virtual Environment

```bash
# Using uv (recommended)
uv venv

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows
```

### 4. Install Dependencies

```bash
# Using uv
uv pip install -e .

# Or using pip
pip install -e .
```

### 5. Start Docker Services

```bash
# From project root
cd ..
docker-compose up -d

# Verify services are running
docker ps
```

You should see:
- `cloudey-postgres` (PostgreSQL)
- `cloudey-redis` (Redis)

---

## ⚙️ Configuration

### 1. Environment Variables

Create `.env` file in the `backend/` directory:

```bash
# === Database Configuration ===
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=cloudey
POSTGRES_USER=cloudey
POSTGRES_PASSWORD=cloudey_dev_password
DATABASE_URL=postgresql://cloudey:cloudey_dev_password@localhost:5432/cloudey

# === Redis Configuration ===
REDIS_HOST=localhost
REDIS_PORT=6379

# === LLM Configuration ===
# Use ONE of these:
ANTHROPIC_API_KEY=sk-ant-...        # For Claude
# OPENAI_API_KEY=sk-...              # For GPT

# === Application ===
ENV=development                       # development, staging, production
LOG_LEVEL=INFO                       # DEBUG, INFO, WARNING, ERROR

# === Security ===
ENCRYPTION_KEY=<generate-with-cryptography>
```

### 2. Generate Encryption Key

```python
# Run in Python shell
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

Copy the output to `ENCRYPTION_KEY` in `.env`.

### 3. Verify Configuration

```bash
# Test database connection
cd backend
python -m app.db.database
```

Expected output:
```
✅ Connected to PostgreSQL: PostgreSQL 16.x...
✅ Database has 15 tables
📊 Tables:
   - users
   - oci_configs
   - oci_compartments
   - oci_compute
   - ...
✅ Database connection test successful!
```

---

## 🗄 Database Setup

### Schema Initialization

The database schema is automatically initialized when the PostgreSQL container starts via:

```sql
backend/app/db/init_schema.sql
```

This file is mounted as a Docker init script and creates:
- All application tables (users, oci_*, sessions, metrics)
- Indexes for performance
- Foreign key constraints

### LangGraph Checkpoint Tables Setup

⚠️ **IMPORTANT**: LangGraph conversation checkpoint tables must be created separately:

```bash
# After starting docker-compose, run the setup script
cd backend
uv run python setup_langgraph.py
```

This creates the LangGraph tables with the correct schema:
- `checkpoints` - Conversation state storage
- `checkpoint_blobs` - Large channel values
- `checkpoint_writes` - Pending writes

**Why separate?** LangGraph's setup uses `CREATE INDEX CONCURRENTLY` which cannot run inside a transaction block. The setup script uses autocommit mode to handle this.

### Manual Schema Reset

If you need to reset the database:

```bash
# Stop and remove containers
docker-compose down -v

# Start fresh
docker-compose up -d

# Re-run LangGraph setup
cd backend
uv run python setup_langgraph.py

# Schema will be re-initialized automatically
```

### Database Migrations

Currently using SQL file-based migrations. For future migrations:

```bash
# Connect to PostgreSQL
docker exec -it cloudey-postgres psql -U cloudey -d cloudey

# Run migration SQL
\i /path/to/migration.sql
```

---

## 🚀 Running the Application

### Development Mode (with hot reload)

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Production Mode

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Background Scheduler

The application automatically starts background jobs:
- **Cost Rollover** - Runs monthly (1st of month at 2 AM)
- **Metrics Sync** - Runs daily (configurable)

View logs:
```bash
tail -f logs/app.log  # If logging to file
```

---

## 📡 API Endpoints

### Base URL
```
http://localhost:8000
```

### Health Check
```http
GET /
```

### User Management
```http
POST   /user                    # Create user
GET    /user/{email}            # Get user by email
POST   /oci-config/{user_id}    # Upload OCI config
GET    /oci-config/{user_id}    # Get OCI config
```

### Resource Sync
```http
POST   /sync/{user_id}                          # Sync all OCI resources
GET    /sync/stats/{user_id}                    # Get sync statistics
GET    /sync/compartments/{user_id}             # List compartments
GET    /sync/compartments/{user_id}/{comp_id}   # Get compartment details
```

### Cost Analytics
```http
GET    /dashboard/{user_id}                     # Dashboard summary
GET    /costs/detailed                          # Detailed cost breakdown
GET    /costs/rollover                          # Manual cost rollover
```

### Recommendations
```http
GET    /recommendations/{user_id}               # AI recommendations
```

### Metrics (Utilization)
```http
POST   /metrics/sync/{user_id}?days=7          # Sync metrics
GET    /metrics/stats/{user_id}                # Metrics cache stats
```

### AI Chat
```http
POST   /chat/stream/{user_id}                  # Streaming chat
  Body: {
    "message": "Show me costs for October",
    "thread_id": "optional-thread-id"
  }
```

### API Documentation

Interactive docs available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 🔄 Application Flow

### 1. Initial Setup Flow

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant API
    participant PostgreSQL
    
    User->>UI: Enter email
    UI->>API: POST /user
    API->>PostgreSQL: Create user record
    PostgreSQL-->>API: user_id
    API-->>UI: Success
    
    User->>UI: Upload OCI config
    UI->>API: POST /oci-config/{user_id}
    API->>API: Encrypt private key
    API->>PostgreSQL: Store config
    PostgreSQL-->>API: config_id
    API-->>UI: Success
    
    User->>UI: Click "Sync Resources"
    UI->>API: POST /sync/{user_id}
    API->>OCI: List compartments
    API->>OCI: List compute instances
    API->>OCI: List volumes
    API->>OCI: List buckets
    API->>OCI: List databases
    API->>OCI: List load balancers
    API->>PostgreSQL: Upsert all resources
    API-->>UI: Sync stats
```

### 2. Cost Tracking Flow

```mermaid
graph TD
    START[User Views Costs Page] --> CHECK_CACHE{Check Redis<br/>Current Month?}
    
    CHECK_CACHE -->|Cache Hit| RETURN_CACHE[Return from Redis]
    CHECK_CACHE -->|Cache Miss| FETCH_OCI[Fetch from OCI Usage API]
    
    FETCH_OCI --> PROCESS[Process Usage Records]
    PROCESS --> CACHE_REDIS[Cache in Redis<br/>TTL: 1 hour]
    CACHE_REDIS --> RETURN_DATA[Return to User]
    
    RETURN_CACHE --> RETURN_DATA
    
    subgraph "Background Job - Monthly"
        SCHEDULE[1st of Month<br/>2:00 AM] --> ROLLOVER[Cost Rollover]
        ROLLOVER --> MOVE[Move Redis → PostgreSQL]
        MOVE --> CLEAR[Clear Redis Cache]
    end
    
    style CHECK_CACHE fill:#fff4e1
    style FETCH_OCI fill:#e1f5ff
    style CACHE_REDIS fill:#ffebee
    style SCHEDULE fill:#f3e5f5
```

### 3. AI Recommendations Flow

```mermaid
graph TD
    USER[User Clicks<br/>AI Insights] --> TRIGGER[API: GET /recommendations]
    
    TRIGGER --> LOAD_COSTS[Load Cost Data<br/>Last 3 Months]
    TRIGGER --> LOAD_RESOURCES[Load Resource Inventory<br/>All Active Resources]
    TRIGGER --> LOAD_METRICS[Load Utilization Metrics<br/>Last 48 Hours]
    
    LOAD_COSTS --> ANALYZE
    LOAD_RESOURCES --> ANALYZE
    LOAD_METRICS --> ANALYZE
    
    subgraph "Analysis Engine"
        ANALYZE[Analyze Data] --> TRENDS[Cost Trends<br/>Month-over-Month]
        ANALYZE --> WASTE[Resource Waste<br/>Stopped, Unattached]
        ANALYZE --> UTIL[Utilization<br/>CPU, Memory, Bandwidth]
        ANALYZE --> OPPS[Opportunities<br/>Reserved, Scheduling]
    end
    
    TRENDS --> GENERATE
    WASTE --> GENERATE
    UTIL --> GENERATE
    OPPS --> GENERATE
    
    GENERATE[Generate Recommendations<br/>with Tables] --> RETURN[Return to User<br/>JSON with Markdown]
    
    style ANALYZE fill:#e8f5e9
    style GENERATE fill:#f3e5f5
```

### 4. AI Chat Flow

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant API
    participant LangGraph
    participant Tools
    participant LLM
    participant PostgreSQL
    
    User->>UI: "Show me costs for bby_prod"
    UI->>API: POST /chat/stream
    API->>PostgreSQL: Load conversation history
    API->>LangGraph: Invoke agent
    
    LangGraph->>LLM: Process user message
    LLM-->>LangGraph: Needs tool: query_cached_costs
    
    LangGraph->>Tools: query_cached_costs("2025-10", compartment="bby_prod")
    Tools->>PostgreSQL: SELECT costs WHERE...
    PostgreSQL-->>Tools: Cost records
    Tools-->>LangGraph: Formatted results
    
    LangGraph->>LLM: Generate response with data
    LLM-->>LangGraph: Natural language answer
    
    LangGraph->>PostgreSQL: Save checkpoint
    LangGraph-->>API: Stream response
    API-->>UI: Server-Sent Events (SSE)
    UI-->>User: Display answer
```

---

## 📁 Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                      # FastAPI app + API routes
│   ├── agents.py                    # LangGraph AI agents
│   ├── prompts.py                   # LLM system prompts
│   ├── models.py                    # Pydantic models
│   ├── sysconfig.py                 # Configuration management
│   ├── logging_config.py            # Logging setup
│   ├── scheduler.py                 # Background job scheduler
│   │
│   ├── dashboard.py                 # Dashboard data aggregation
│   ├── detailed_costs.py            # Cost breakdown logic
│   ├── recommendations_engine.py    # AI recommendations generator
│   │
│   ├── cache/                       # Caching layer
│   │   ├── redis_cache.py          # Redis client
│   │   ├── cost_cache_manager.py   # Cost caching logic
│   │   └── cost_rollover.py        # Monthly rollover job
│   │
│   ├── cloud/                       # Cloud provider integrations
│   │   ├── oci/                    # Oracle Cloud Infrastructure
│   │   │   ├── client.py           # Base OCI client
│   │   │   ├── config.py           # OCI config loader
│   │   │   ├── rate_limiter.py     # API rate limiting
│   │   │   ├── compartment.py      # Compartment client
│   │   │   ├── compute.py          # Compute client
│   │   │   ├── block_storage.py    # Block Storage client
│   │   │   ├── object_storage.py   # Object Storage client
│   │   │   ├── file_storage.py     # File Storage client
│   │   │   ├── database.py         # Database client
│   │   │   ├── postgresql.py       # PostgreSQL DB client
│   │   │   ├── load_balancer.py    # Load Balancer client
│   │   │   ├── monitoring.py       # Monitoring client
│   │   │   ├── usage_api_client.py # Usage API client
│   │   │   ├── pricing_client.py   # Pricing data
│   │   │   ├── resource_sync.py    # Resource sync orchestrator
│   │   │   ├── metrics_sync.py     # Metrics sync orchestrator
│   │   │   ├── cache_warming.py    # Cache warming strategies
│   │   │   ├── ai_cache_tools.py   # AI tools for cached data
│   │   │   ├── tools.py            # AI tools for OCI API
│   │   │   └── optimization.py     # Cost optimization helpers
│   │   └── aws/                    # AWS (future)
│   │
│   ├── db/                          # Database layer
│   │   ├── database.py             # PostgreSQL connection
│   │   ├── init_schema.sql         # Database schema
│   │   ├── crud.py                 # User & config CRUD
│   │   ├── resource_crud.py        # Resource CRUD operations
│   │   ├── cost_cache_crud.py      # Cost data CRUD
│   │   └── metrics_crud.py         # Metrics CRUD
│   │
│   └── utils/                       # Utilities
│       └── encryption.py           # Cryptography helpers
│
├── pyproject.toml                   # Project dependencies
├── uv.lock                          # Locked dependencies
├── .env                             # Environment variables (gitignored)
├── .gitignore
├── .python-version
└── README.md                        # This file
```

---

## 🔑 Key Components

### 1. **FastAPI Application** (`main.py`)

The main application entry point with:
- CORS middleware for frontend integration
- API route definitions
- Lifespan context for startup/shutdown
- Background scheduler initialization

Key features:
```python
@app.on_event("startup")
async def startup_event():
    # Initialize database connection
    # Start background scheduler
    # Initialize LangGraph checkpointer
    # Warm up Redis cache
```

### 2. **LangGraph Agents** (`agents.py`)

AI agent orchestration with:
- **Tool-calling agents** - Can query databases, call APIs
- **Conversation persistence** - PostgreSQL checkpoints
- **Streaming responses** - Server-Sent Events

Tools available to agents:
- `query_cached_costs` - Fast cost queries from Redis/PostgreSQL
- `query_resource_inventory` - List instances, volumes, buckets
- `analyze_cost_trends` - Month-over-month comparisons
- `get_top_cost_drivers` - Identify expensive services
- `list_oci_compartments` - List all compartments
- `get_oci_cost_summary` - Cost aggregation
- `list_oci_compute_instances` - Live OCI API calls

### 3. **Resource Sync** (`cloud/oci/resource_sync.py`)

Orchestrates syncing of OCI resources:
1. **Compartments** - Organizational units
2. **Compute Instances** - VMs
3. **Volumes** - Block storage
4. **Buckets** - Object storage
5. **File Storage** - FSS
6. **Databases** - Oracle DB
7. **PostgreSQL** - Managed PostgreSQL
8. **Load Balancers** - LBs

Implements:
- Upsert logic (insert or update)
- Soft delete marking (`is_deleted`)
- Error handling per service
- Progress tracking

### 4. **Metrics Sync** (`cloud/oci/metrics_sync.py`)

Fetches utilization data from OCI Monitoring:

**For Compute Instances:**
- `CpuUtilization` (%)
- `MemoryUtilization` (%)

**For Load Balancers:**
- `PeakBandwidth` (Mbps)

Stores in `oci_metrics` table with:
- Aggregation type (mean, max, min)
- Time period (start/end)
- Automatic cleanup (30-day retention)

### 5. **Recommendations Engine** (`recommendations_engine.py`)

Generates AI-powered recommendations:

**Types of Recommendations:**
1. **Cost Trend Insights** - Month-over-month analysis
2. **Dominant Service Analysis** - Top cost drivers
3. **Stopped Instances** - Unused resources
4. **Unattached Volumes** - Orphaned storage
5. **Large Volumes** - Performance tier optimization
6. **Instance Rightsizing** - Underutilized instances (with metrics)
7. **Non-Prod Scheduling** - Dev/test/UAT instances
8. **Underutilized Load Balancers** - Low-bandwidth LBs
9. **Reserved Capacity** - 1-year commitment savings
10. **Object Storage Tiers** - Archive tier opportunities

Each recommendation includes:
- Severity (high, medium, low)
- Potential savings ($)
- Detailed table with resources
- Specific action items

### 6. **Cost Cache Manager** (`cache/cost_cache_manager.py`)

Hybrid caching strategy:
- **Redis** - Current month (fast, TTL: 1 hour)
- **PostgreSQL** - Historical months (permanent)

Key methods:
- `get_cached_costs()` - Retrieve from cache
- `cache_current_month()` - Store in Redis
- `rollover_month()` - Move Redis → PostgreSQL
- `warm_cache()` - Pre-populate Redis

### 7. **Database Layer** (`db/`)

**PostgreSQL Schema:**
- **15 tables** - Users, configs, resources, costs, metrics, checkpoints
- **Foreign keys** - Referential integrity
- **Indexes** - Performance optimization
- **UNIQUE constraints** - Prevent duplicates

**CRUD Operations:**
- `crud.py` - Users, OCI configs, sessions
- `resource_crud.py` - Resources (upsert, mark deleted)
- `cost_cache_crud.py` - Cost data
- `metrics_crud.py` - Utilization metrics

---

## 🔧 Troubleshooting

### Common Issues

#### 1. **Database Connection Failed**

**Error:**
```
psycopg2.OperationalError: connection to server at "localhost", port 5432 failed
```

**Solutions:**
```bash
# Check if PostgreSQL is running
docker ps | grep postgres

# Check PostgreSQL logs
docker logs cloudey-postgres

# Verify .env configuration
cat .env | grep POSTGRES

# Restart PostgreSQL
docker-compose restart postgres
```

#### 2. **Redis Connection Failed**

**Error:**
```
redis.exceptions.ConnectionError: Error connecting to Redis
```

**Solutions:**
```bash
# Check if Redis is running
docker ps | grep redis

# Test Redis connection
docker exec -it cloudey-redis redis-cli ping
# Should return: PONG

# Restart Redis
docker-compose restart redis
```

#### 3. **OCI API Rate Limiting**

**Error:**
```
oci.exceptions.ServiceError: TooManyRequests (429)
```

**Solutions:**
```python
# Adjust rate limiter in cloud/oci/rate_limiter.py
class RateLimiter:
    def __init__(self):
        self.min_interval = 0.5  # Increase to 1.0 or 2.0
```

#### 4. **LangGraph Checkpoint Errors**

**Error:**
```
psycopg.errors.UndefinedTable: relation "checkpoints" does not exist
```

**Solutions:**
```bash
# Check if schema was initialized
docker exec cloudey-postgres psql -U cloudey -d cloudey -c "\dt"

# If missing, reinitialize database
docker-compose down -v
docker-compose up -d
```

#### 5. **Import Errors**

**Error:**
```
ModuleNotFoundError: No module named 'oci'
```

**Solutions:**
```bash
# Verify virtual environment is activated
which python  # Should show .venv path

# Reinstall dependencies
uv pip install -e .

# Or use pip
pip install -e .
```

#### 6. **Encryption Key Errors**

**Error:**
```
cryptography.fernet.InvalidToken: Invalid encryption key
```

**Solutions:**
```bash
# Generate new encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Update .env
ENCRYPTION_KEY=<new-key>

# Re-upload OCI config in UI
```

#### 7. **Metrics Sync Fails**

**Error:**
```
TypeError: '<' not supported between instances of 'NoneType' and 'NoneType'
```

**Solutions:**
- This is usually due to missing `vcpus` or `size_in_gbs` in resources
- Ensure all resources have been synced successfully
- Check for partial sync failures in logs

#### 8. **Background Scheduler Not Running**

**Check:**
```bash
# Look for scheduler logs
tail -f logs/app.log | grep scheduler

# Verify APScheduler is initialized
# Should see: "Scheduler started"
```

**Debug:**
```python
# In app/scheduler.py, add more logging
scheduler.add_job(...)
logger.info(f"Added job: {job.id}")
```

### Debugging Tips

#### Enable Debug Logging

```bash
# In .env
LOG_LEVEL=DEBUG

# Restart application
```

#### Check PostgreSQL Data

```bash
# Connect to database
docker exec -it cloudey-postgres psql -U cloudey -d cloudey

# Check table counts
SELECT 'users' as table_name, COUNT(*) FROM users
UNION ALL SELECT 'oci_compute', COUNT(*) FROM oci_compute
UNION ALL SELECT 'oci_costs', COUNT(*) FROM oci_costs;

# Check recent costs
SELECT service, SUM(cost) as total, COUNT(*) 
FROM oci_costs 
WHERE month = '2025-10' 
GROUP BY service 
ORDER BY total DESC;
```

#### Check Redis Cache

```bash
# Connect to Redis
docker exec -it cloudey-redis redis-cli

# List all keys
KEYS *

# Get specific key
GET "costs:user_1:2025-10"

# Check TTL
TTL "costs:user_1:2025-10"
```

#### Test OCI Connectivity

```python
# Python shell
from app.cloud.oci.compartment import CompartmentClient

client = CompartmentClient(user_id=1)
compartments = client.list_compartments()
print(f"Found {len(compartments)} compartments")
```

---

## 💻 Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_recommendations.py
```

### Code Quality

```bash
# Format code
black app/

# Check linting
ruff check app/

# Type checking
mypy app/
```

### Adding a New OCI Service

1. **Create client file** (`cloud/oci/new_service.py`)
```python
from app.cloud.oci.client import OCIClient

class NewServiceClient(OCIClient):
    def list_resources(self, compartment_id: str):
        # Implementation
        pass
```

2. **Add database table** (`db/init_schema.sql`)
```sql
CREATE TABLE IF NOT EXISTS oci_new_service (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ocid TEXT NOT NULL,
    -- other fields
    UNIQUE(user_id, ocid)
);
```

3. **Add CRUD operations** (`db/resource_crud.py`)
```python
def upsert_new_service(user_id: int, resource: Dict):
    # Implementation
    pass
```

4. **Update sync** (`cloud/oci/resource_sync.py`)
```python
# In sync_user_resources()
new_service_client = NewServiceClient(user_id)
for comp in compartments:
    resources = new_service_client.list_resources(comp['ocid'])
    for res in resources:
        upsert_new_service(user_id, res)
```

5. **Restart services**
```bash
docker-compose down -v  # Reset database
docker-compose up -d
```

### Database Migration Workflow

1. **Modify schema** (`db/init_schema.sql`)
2. **Reset database**
```bash
docker-compose down -v
docker-compose up -d
```
3. **Test migration**
```bash
python -m app.db.database  # Verify tables
```

### API Development

1. **Add new endpoint** (`main.py`)
```python
@app.get("/new-endpoint/{user_id}")
async def new_endpoint(user_id: int):
    # Implementation
    return {"status": "success"}
```

2. **Test endpoint**
```bash
curl http://localhost:8000/new-endpoint/1
```

3. **Check OpenAPI docs**
- http://localhost:8000/docs

---

## 📚 Additional Resources

### Documentation
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [LangGraph Docs](https://langchain-ai.github.io/langgraph/)
- [OCI Python SDK](https://docs.oracle.com/en-us/iaas/tools/python/latest/)
- [PostgreSQL Docs](https://www.postgresql.org/docs/)
- [Redis Docs](https://redis.io/docs/)

### Related Files
- Frontend README: `../frontend/README.md`
- Docker Compose: `../docker-compose.yml`
- Schema: `app/db/init_schema.sql`

---

## 📝 Notes

### Performance Considerations

- **Redis TTL**: Set to 1 hour for current month costs
- **Metrics Retention**: 30 days (configurable)
- **API Rate Limiting**: ~2 requests/second to OCI
- **Database Indexing**: Optimized for common queries

### Security Best Practices

- ✅ OCI private keys encrypted at rest (Fernet)
- ✅ Environment variables for secrets (not in code)
- ✅ HTTPS recommended for production
- ✅ Rate limiting on API endpoints
- ⚠️ No authentication layer (add JWT for production)

### Future Enhancements

- [ ] Add AWS support
- [ ] Implement user authentication (JWT)
- [ ] Add email notifications for cost anomalies
- [ ] Create cost forecasting models
- [ ] Add Terraform integration for auto-remediation
- [ ] Implement multi-tenancy
- [ ] Add Grafana dashboards

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Write tests
5. Submit a pull request

---

## 📄 License

Proprietary - All rights reserved

---

## 👥 Support

For questions or issues:
- **Email**: isma@gonrod.com
- **Issues**: https://github.com/ismgonza/cloudey-backend/issues

---

**Built with ❤️ by the Cloudey team**

