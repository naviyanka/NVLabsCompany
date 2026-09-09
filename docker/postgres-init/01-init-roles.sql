-- Initialize database roles for NEXUS (WP-8)
-- PostgreSQL 16+ requires dedicated schema ownership & explicit grant structure.

-- 1. Migrator role: owns schema public, runs Alembic migrations
CREATE ROLE nexus_migrator LOGIN PASSWORD 'nexus_migrator_pass';
GRANT ALL ON SCHEMA public TO nexus_migrator;
ALTER SCHEMA public OWNER TO nexus_migrator;

-- 2. System worker role: holds BYPASSRLS for cross-tenant discovery and maintenance
CREATE ROLE nexus_system LOGIN PASSWORD 'nexus_system_pass' BYPASSRLS;
GRANT USAGE ON SCHEMA public TO nexus_system;

-- 3. Application role: standard least-privilege, subject to RLS (NO BYPASSRLS)
CREATE ROLE nexus_app LOGIN PASSWORD 'nexus_app_pass';
GRANT USAGE ON SCHEMA public TO nexus_app;

-- 4. Default privileges for objects created in schema public by nexus_migrator
ALTER DEFAULT PRIVILEGES FOR ROLE nexus_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_app;

ALTER DEFAULT PRIVILEGES FOR ROLE nexus_migrator IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO nexus_app;

ALTER DEFAULT PRIVILEGES FOR ROLE nexus_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nexus_system;

ALTER DEFAULT PRIVILEGES FOR ROLE nexus_migrator IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO nexus_system;

-- Grant permissions on any pre-existing tables/sequences in public
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nexus_app, nexus_system;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO nexus_app, nexus_system;
