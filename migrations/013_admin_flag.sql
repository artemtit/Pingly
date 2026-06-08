-- Admin access flag for the internal admin panel (/admin).
-- Applied to the remote DB via Supabase MCP; kept here for the record.
alter table users add column if not exists is_admin boolean not null default false;

-- Grant the founder admin rights (Telegram id of @ligr5 / SUPPORT_TG_ID).
update users set is_admin = true where tg_id = 2091126912;
