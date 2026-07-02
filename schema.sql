CREATE TABLE IF NOT EXISTS guild_config (
    guild_id BIGINT PRIMARY KEY,
    partner_channel BIGINT,
    ad_channel BIGINT,
    member_role BIGINT,
    partner_ping_role BIGINT,
    log_channel BIGINT,
    partner_delay INTEGER DEFAULT 21600
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

CREATE TABLE IF NOT EXISTS partnerships (
    id BIGSERIAL PRIMARY KEY,
    guild1_id BIGINT NOT NULL,
    guild2_id BIGINT NOT NULL,
    guild1_name TEXT,
    guild2_name TEXT,
    guild1_members INTEGER,
    guild2_members INTEGER,
    guild1_ping TEXT,
    guild2_ping TEXT,
    host_guild_id BIGINT,
    partnered_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reports (
    id BIGSERIAL PRIMARY KEY,
    partnership_id BIGINT,
    reporter_id BIGINT NOT NULL,
    reporter_guild_id BIGINT,
    reported_guild_id BIGINT NOT NULL,
    category TEXT,
    reason TEXT NOT NULL,
    evidence TEXT,
    status TEXT DEFAULT 'open',
    handled_by BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS reports_partnership_reporter_idx
    ON reports (partnership_id, reporter_id);

CREATE TABLE IF NOT EXISTS premium (
    guild_id   BIGINT PRIMARY KEY,
    available_pings TEXT[] DEFAULT '{}',
    added_by   BIGINT NOT NULL,
    added_at   TIMESTAMPTZ DEFAULT NOW()
);
