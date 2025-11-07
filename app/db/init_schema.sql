-- Cloudey PostgreSQL Schema
-- Production-ready database schema for OCI cost tracking

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- USERS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- OCI CONFIG TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_configs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenancy_ocid TEXT NOT NULL,
    user_ocid TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    region VARCHAR(50) NOT NULL,
    private_key_encrypted TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)
);

CREATE INDEX idx_oci_configs_user ON oci_configs(user_id);

-- ============================================================================
-- OCI COMPARTMENTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_compartments (
    ocid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    lifecycle_state TEXT,
    time_created TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_compartments_user ON oci_compartments(user_id);
CREATE INDEX idx_compartments_name ON oci_compartments(name);

-- ============================================================================
-- OCI COMPUTE INSTANCES TABLE (renamed from oci_instances)
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_compute (
    ocid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    compartment_ocid TEXT NOT NULL REFERENCES oci_compartments(ocid),
    display_name TEXT NOT NULL,
    shape TEXT,
    lifecycle_state TEXT,
    availability_domain TEXT,
    vcpus INTEGER,
    memory_in_gbs REAL,
    region TEXT,
    time_created TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_compute_user ON oci_compute(user_id);
CREATE INDEX idx_compute_compartment ON oci_compute(compartment_ocid);
CREATE INDEX idx_compute_state ON oci_compute(lifecycle_state);

-- ============================================================================
-- OCI VOLUMES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_volumes (
    ocid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    compartment_ocid TEXT NOT NULL REFERENCES oci_compartments(ocid),
    display_name TEXT NOT NULL,
    size_in_gbs INTEGER,
    lifecycle_state TEXT,
    availability_domain TEXT,
    region TEXT,
    time_created TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_volumes_user ON oci_volumes(user_id);
CREATE INDEX idx_volumes_compartment ON oci_volumes(compartment_ocid);
CREATE INDEX idx_volumes_state ON oci_volumes(lifecycle_state);

-- ============================================================================
-- OCI BUCKETS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_buckets (
    ocid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    compartment_ocid TEXT NOT NULL REFERENCES oci_compartments(ocid),
    name TEXT NOT NULL,
    namespace TEXT,
    region TEXT,
    time_created TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_buckets_user ON oci_buckets(user_id);
CREATE INDEX idx_buckets_compartment ON oci_buckets(compartment_ocid);

-- ============================================================================
-- OCI FILE STORAGE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_file_storage (
    ocid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    compartment_ocid TEXT NOT NULL REFERENCES oci_compartments(ocid),
    display_name TEXT NOT NULL,
    metered_bytes BIGINT,
    lifecycle_state TEXT,
    availability_domain TEXT,
    region TEXT,
    time_created TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_file_storage_user ON oci_file_storage(user_id);
CREATE INDEX idx_file_storage_compartment ON oci_file_storage(compartment_ocid);

-- ============================================================================
-- OCI DATABASE TABLE (Oracle DB Systems)
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_database (
    ocid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    compartment_ocid TEXT NOT NULL REFERENCES oci_compartments(ocid),
    display_name TEXT NOT NULL,
    db_system_shape TEXT,
    database_edition TEXT,
    lifecycle_state TEXT,
    availability_domain TEXT,
    cpu_core_count INTEGER,
    data_storage_size_in_gbs INTEGER,
    region TEXT,
    time_created TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_database_user ON oci_database(user_id);
CREATE INDEX idx_database_compartment ON oci_database(compartment_ocid);
CREATE INDEX idx_database_state ON oci_database(lifecycle_state);

-- ============================================================================
-- OCI POSTGRESQL DATABASE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_database_psql (
    ocid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    compartment_ocid TEXT NOT NULL REFERENCES oci_compartments(ocid),
    display_name TEXT NOT NULL,
    shape TEXT,
    instance_count INTEGER,
    storage_details_iops BIGINT,
    storage_details_size_in_gbs INTEGER,
    lifecycle_state TEXT,
    region TEXT,
    time_created TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_database_psql_user ON oci_database_psql(user_id);
CREATE INDEX idx_database_psql_compartment ON oci_database_psql(compartment_ocid);
CREATE INDEX idx_database_psql_state ON oci_database_psql(lifecycle_state);

-- ============================================================================
-- OCI LOAD BALANCER TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_load_balancer (
    ocid TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    compartment_ocid TEXT NOT NULL REFERENCES oci_compartments(ocid),
    display_name TEXT NOT NULL,
    shape_name TEXT,
    is_private BOOLEAN,
    ip_addresses JSONB,
    lifecycle_state TEXT,
    region TEXT,
    time_created TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_load_balancer_user ON oci_load_balancer(user_id);
CREATE INDEX idx_load_balancer_compartment ON oci_load_balancer(compartment_ocid);
CREATE INDEX idx_load_balancer_state ON oci_load_balancer(lifecycle_state);

-- ============================================================================
-- OCI COSTS TABLE (renamed from oci_cost_cache)
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_costs (
    resource_ocid TEXT NOT NULL,
    service TEXT NOT NULL,
    month TEXT NOT NULL,
    cost REAL NOT NULL,
    is_complete BOOLEAN DEFAULT FALSE,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (resource_ocid, month)
);

CREATE INDEX idx_costs_month ON oci_costs(month);
CREATE INDEX idx_costs_service ON oci_costs(service, month);
CREATE INDEX idx_costs_resource ON oci_costs(resource_ocid);

-- ============================================================================
-- SESSIONS TABLE (for chat conversations)
-- ============================================================================
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_updated ON sessions(updated_at DESC);

-- ============================================================================
-- LANGGRAPH CHECKPOINTS (for conversation state)
-- ============================================================================
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint BYTEA,
    metadata BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE INDEX idx_checkpoints_thread ON checkpoints(thread_id);

-- ============================================================================
-- LANGGRAPH WRITES (for conversation writes)
-- ============================================================================
CREATE TABLE IF NOT EXISTS writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    value BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX idx_writes_thread ON writes(thread_id, checkpoint_ns, checkpoint_id);

-- ============================================================================
-- OCI METRICS (for monitoring data)
-- ============================================================================
CREATE TABLE IF NOT EXISTS oci_metrics (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resource_ocid TEXT NOT NULL,
    resource_type VARCHAR(50) NOT NULL, -- 'compute', 'load_balancer'
    metric_name VARCHAR(100) NOT NULL,  -- 'CpuUtilization', 'MemoryUtilization', 'ActiveConnections', etc.
    metric_value DECIMAL(10, 2),
    aggregation_type VARCHAR(20) DEFAULT 'mean', -- 'mean', 'max', 'min', 'sum'
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(resource_ocid, metric_name, aggregation_type, period_start)
);

CREATE INDEX idx_metrics_resource ON oci_metrics(resource_ocid);
CREATE INDEX idx_metrics_user ON oci_metrics(user_id);
CREATE INDEX idx_metrics_type ON oci_metrics(resource_type);
CREATE INDEX idx_metrics_fetched ON oci_metrics(fetched_at);

-- ============================================================================
-- No seed users - users are created via the application
-- ============================================================================

