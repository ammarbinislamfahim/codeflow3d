-- PostgreSQL Schema for CodeFlow3D SaaS

-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- API Keys table (per-user rate limiting)
CREATE TABLE api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash VARCHAR(64) UNIQUE NOT NULL,
    key_prefix VARCHAR(20),
    name VARCHAR(255),
    rate_limit_per_minute INTEGER DEFAULT 10,
    rate_limit_per_day INTEGER DEFAULT 1000,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);

-- Flow Graph Analysis History
CREATE TABLE analyses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    api_key_id INTEGER NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    language VARCHAR(50) NOT NULL,
    code_hash VARCHAR(64),
    code_length INTEGER NOT NULL,
    node_count INTEGER,
    edge_count INTEGER,
    loop_count INTEGER,
    conditional_count INTEGER,
    execution_time_ms INTEGER,
    status VARCHAR(50),
    error_message TEXT,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Saved Graphs
CREATE TABLE saved_graphs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_id INTEGER REFERENCES analyses(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    language VARCHAR(50),
    code TEXT NOT NULL,
    graph_data JSONB,
    is_public BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Subscriptions (billing tiers)
CREATE TABLE subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    plan VARCHAR(50) DEFAULT 'free',
    requests_per_day INTEGER DEFAULT 100,
    requests_per_month INTEGER DEFAULT 3000,
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indices
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_api_keys_key ON api_keys(key_hash);
CREATE INDEX idx_analyses_user_id ON analyses(user_id);
CREATE INDEX idx_analyses_created_at ON analyses(created_at);
CREATE INDEX idx_analyses_code_hash ON analyses(code_hash);
CREATE INDEX idx_saved_graphs_user_id ON saved_graphs(user_id);
CREATE INDEX idx_saved_graphs_is_public ON saved_graphs(is_public);
CREATE INDEX idx_subscriptions_user ON subscriptions(user_id);