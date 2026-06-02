-- 009_email_verification.sql
-- Email confirmation codes for registration. A new email account stays
-- email_verified=false until the user enters the 6-digit code we email them.
-- Safe to run multiple times.

alter table users add column if not exists email_verified boolean not null default false;
alter table users add column if not exists verification_code text;
alter table users add column if not exists verification_expires_at timestamptz;

-- Backfill: every EXISTING account is considered verified, so nobody is locked
-- out when the feature turns on (only new registrations go through the code).
update users set email_verified = true where email_verified = false;
