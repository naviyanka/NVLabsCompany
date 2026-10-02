-- Move NEXUS schema objects from the application role to the migrator role.
--
-- For installations that were migrated while the application role was in charge (the
-- Helm migration job used the application credential), so nexus_app owns the tables. An
-- owner can drop triggers, disable row level security and alter policies, so ownership is
-- the thing to move. Run by a database administrator only, never from an application pod.
--
-- It does a dry run by default and changes nothing. Read the NOTICE lines, then re-run
-- with nexus.remediation_mode=apply. The apply runs in one transaction: if anything it
-- cannot move is left, or the application role still owns something at the end, the whole
-- run rolls back.
--
-- Scope, deliberately narrow:
--   moved   in schema public, owned by the application role, and not part of an extension:
--           the schema, tables, partitioned tables, views, sequences (a sequence owned by a
--           table column follows its table), functions, procedures, enum and domain types.
--           Indexes, constraints, triggers, policies and row level security move with their
--           table and are untouched. Rows and the alembic_version row are never read.
--   listed  as [manual] and not moved: the database itself, default privileges the
--           application role set, objects in any other schema, and any other object kind.
--           A run that lists any [manual] object refuses to apply.
-- There is no REASSIGN OWNED. A role's other objects are never swept in.
--
-- After the move, the application and system roles get exactly the privileges that
-- provision-roles.sql gives them on new objects, and nothing else on the moved relations.
-- The exception is alembic_version, which only the migrator may touch.
-- The previous privileges are printed as [acl] in the dry run, because they are replaced.
--
-- Inputs, as session settings: nexus.remediation_mode (report or apply, default report),
-- and the optional role names nexus.migrator_role, nexus.app_role and nexus.system_role.
--
--   PGOPTIONS="-c nexus.remediation_mode=apply" \
--     psql -v ON_ERROR_STOP=1 -d nexus -f deploy/postgres/remediate-ownership.sql

DO $remediate$
DECLARE
    migrator text := coalesce(nullif(current_setting('nexus.migrator_role', true), ''), 'nexus_migrator');
    app text := coalesce(nullif(current_setting('nexus.app_role', true), ''), 'nexus_app');
    sys text := coalesce(nullif(current_setting('nexus.system_role', true), ''), 'nexus_system');
    mode text := coalesce(nullif(current_setting('nexus.remediation_mode', true), ''), 'report');
    item record;
    rel record;
    manual_count integer;
    moved integer := 0;
    remaining integer;
BEGIN
    IF mode NOT IN ('report', 'apply') THEN
        RAISE EXCEPTION 'nexus.remediation_mode must be report or apply, not %', mode;
    END IF;
    IF migrator = app OR migrator = sys OR app = sys THEN
        RAISE EXCEPTION 'the migrator, application and system roles must be three different roles';
    END IF;
    IF (SELECT count(*) FROM pg_roles WHERE rolname IN (migrator, app, sys)) <> 3 THEN
        RAISE EXCEPTION 'run provision-roles.sql first: one of the three roles does not exist';
    END IF;
    IF to_regclass('public.alembic_version') IS NULL THEN
        RAISE EXCEPTION 'public.alembic_version does not exist, so this is not a NEXUS database';
    END IF;

    -- Everything the application role owns, in one place: the dry run prints it, the apply
    -- moves the [transfer] rows, and the final check reruns it and expects nothing.
    CREATE FUNCTION pg_temp.nexus_inventory(app text, migrator text)
    RETURNS TABLE (kind text, ident text, action text, ddl text, acl text)
    LANGUAGE sql AS $inv$
        WITH a AS (SELECT oid FROM pg_roles WHERE rolname = app)
        SELECT 'schema'::text, n.nspname::text, 'transfer'::text,
               format('ALTER SCHEMA %I OWNER TO %I', n.nspname, migrator), n.nspacl::text
          FROM pg_namespace n, a WHERE n.nspname = 'public' AND n.nspowner = a.oid
        UNION ALL
        SELECT CASE c.relkind WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned table'
                              WHEN 'v' THEN 'view' WHEN 'S' THEN 'sequence' ELSE 'relation' END,
               c.oid::regclass::text,
               CASE WHEN c.relkind IN ('r', 'p', 'v', 'S') THEN 'transfer' ELSE 'manual' END,
               CASE c.relkind
                   WHEN 'r' THEN format('ALTER TABLE %s OWNER TO %I', c.oid::regclass, migrator)
                   WHEN 'p' THEN format('ALTER TABLE %s OWNER TO %I', c.oid::regclass, migrator)
                   WHEN 'v' THEN format('ALTER VIEW %s OWNER TO %I', c.oid::regclass, migrator)
                   WHEN 'S' THEN format('ALTER SEQUENCE %s OWNER TO %I', c.oid::regclass, migrator)
               END,
               c.relacl::text
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, a
         WHERE c.relowner = a.oid AND n.nspname = 'public'
           -- Indexes and TOAST tables follow their table. A sequence owned by a column
           -- follows its table and cannot be moved on its own.
           AND c.relkind NOT IN ('i', 'I', 't')
           AND NOT (c.relkind = 'S' AND EXISTS (
                 SELECT 1 FROM pg_depend d
                  WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                    AND d.deptype IN ('a', 'i')))
           AND NOT EXISTS (
                 SELECT 1 FROM pg_depend d
                  WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
        UNION ALL
        SELECT CASE p.prokind WHEN 'p' THEN 'procedure' ELSE 'function' END,
               p.oid::regprocedure::text,
               CASE WHEN p.prokind IN ('f', 'p') THEN 'transfer' ELSE 'manual' END,
               CASE p.prokind
                   WHEN 'f' THEN format('ALTER FUNCTION %s OWNER TO %I', p.oid::regprocedure, migrator)
                   WHEN 'p' THEN format('ALTER PROCEDURE %s OWNER TO %I', p.oid::regprocedure, migrator)
               END,
               p.proacl::text
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace, a
         WHERE p.proowner = a.oid AND n.nspname = 'public'
           AND NOT EXISTS (
                 SELECT 1 FROM pg_depend d
                  WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
        UNION ALL
        SELECT 'type', t.oid::regtype::text,
               CASE WHEN t.typtype IN ('e', 'd') THEN 'transfer' ELSE 'manual' END,
               CASE t.typtype
                   WHEN 'e' THEN format('ALTER TYPE %s OWNER TO %I', t.oid::regtype, migrator)
                   WHEN 'd' THEN format('ALTER DOMAIN %s OWNER TO %I', t.oid::regtype, migrator)
               END,
               t.typacl::text
          FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace, a
         WHERE t.typowner = a.oid AND n.nspname = 'public'
           AND t.typtype IN ('e', 'd', 'b', 'r', 'm') AND t.typcategory <> 'A'
           AND NOT EXISTS (
                 SELECT 1 FROM pg_depend d
                  WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')
        UNION ALL
        SELECT 'database', d.datname::text, 'manual', NULL, d.datacl::text
          FROM pg_database d, a WHERE d.datname = current_database() AND d.datdba = a.oid
        UNION ALL
        SELECT 'default privileges', coalesce(n.nspname::text, 'all schemas'), 'manual', NULL, x.defaclacl::text
          FROM pg_default_acl x LEFT JOIN pg_namespace n ON n.oid = x.defaclnamespace, a
         WHERE x.defaclrole = a.oid
        UNION ALL
        SELECT 'schema', n.nspname::text, 'manual', NULL, n.nspacl::text
          FROM pg_namespace n, a
         WHERE n.nspowner = a.oid AND n.nspname NOT IN ('public', 'information_schema')
           AND n.nspname NOT LIKE 'pg\_%'
        UNION ALL
        SELECT 'relation in another schema', c.oid::regclass::text, 'manual', NULL, c.relacl::text
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, a
         WHERE c.relowner = a.oid AND c.relkind NOT IN ('i', 'I', 't')
           AND n.nspname NOT IN ('public', 'information_schema') AND n.nspname NOT LIKE 'pg\_%'
    $inv$;

    FOR item IN SELECT * FROM pg_temp.nexus_inventory(app, migrator) ORDER BY action DESC, kind, ident LOOP
        RAISE NOTICE '[%] % %', item.action, item.kind, item.ident;
        IF item.acl IS NOT NULL THEN
            RAISE NOTICE '[acl]   previous privileges of % are %', item.ident, item.acl;
        END IF;
    END LOOP;
    SELECT count(*) INTO manual_count FROM pg_temp.nexus_inventory(app, migrator) WHERE action = 'manual';

    IF mode = 'report' THEN
        RAISE NOTICE 'dry run: nothing was changed. % object(s) need manual attention.', manual_count;
    ELSE
        IF manual_count > 0 THEN
            RAISE EXCEPTION 'refusing to apply: % object(s) listed as [manual] must be handled by hand first', manual_count;
        END IF;

        -- The relations that are moving, including sequences that follow their table, so
        -- that only they get their privileges reset afterwards.
        CREATE TEMP TABLE nexus_moving ON COMMIT DROP AS
            SELECT c.oid AS oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = app)
               AND c.relkind IN ('r', 'p', 'v', 'S')
               AND NOT EXISTS (
                     SELECT 1 FROM pg_depend d
                      WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e');

        FOR item IN SELECT * FROM pg_temp.nexus_inventory(app, migrator) WHERE action = 'transfer' ORDER BY kind, ident LOOP
            EXECUTE item.ddl;
            moved := moved + 1;
        END LOOP;

        FOR rel IN
            SELECT c.oid::regclass::text AS name, c.relkind
              FROM pg_class c JOIN nexus_moving m ON m.oid = c.oid
        LOOP
            IF rel.relkind = 'S' THEN
                EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM %I, %I', rel.name, app, sys);
                EXECUTE format('GRANT USAGE, SELECT, UPDATE ON SEQUENCE %s TO %I, %I', rel.name, app, sys);
            ELSE
                EXECUTE format('REVOKE ALL ON TABLE %s FROM %I, %I', rel.name, app, sys);
                EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %s TO %I, %I', rel.name, app, sys);
            END IF;
        END LOOP;
        -- The migration version table is for the migrator alone, as nexus.db_migrate leaves it.
        EXECUTE format('REVOKE ALL ON TABLE public.alembic_version FROM %I, %I', app, sys);

        SELECT count(*) INTO remaining FROM pg_temp.nexus_inventory(app, migrator);
        IF remaining > 0 THEN
            RAISE EXCEPTION 'rolled back: % object(s) are still owned by %', remaining, app;
        END IF;
        IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'public.alembic_version'::regclass)
               <> migrator THEN
            RAISE EXCEPTION 'rolled back: public.alembic_version is not owned by %', migrator;
        END IF;
        RAISE NOTICE 'applied: % object(s) now owned by %. The application role owns nothing.', moved, migrator;
    END IF;
END
$remediate$;
