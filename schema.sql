CREATE TABLE IF NOT EXISTS guild_config (
    guild_id BIGINT PRIMARY KEY,
    partner_channel BIGINT,
    ad_channel BIGINT,
    member_role BIGINT,
    partner_ping_role BIGINT,
    log_channel BIGINT,
    partner_delay INTEGER DEFAULT 21600,
    premium BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS blacklists (
    guild_id BIGINT PRIMARY KEY,
    reason TEXT NOT NULL,
    added_by BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS whitelisted_links (
    link TEXT PRIMARY KEY,
    added_by BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS early_access (
    guild_id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS premium (
    guild_id   BIGINT PRIMARY KEY,
    available_pings TEXT[] DEFAULT '{}',
    added_by   BIGINT NOT NULL,
    added_at   TIMESTAMPTZ DEFAULT NOW()
);
