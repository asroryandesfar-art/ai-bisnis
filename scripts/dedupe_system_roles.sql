-- One-time cleanup: roles.UNIQUE(org_id, key) never fires for org_id IS NULL
-- (Postgres treats NULLs as distinct), so every migrate_database.sh re-run
-- since this project started inserted a fresh duplicate row per system role
-- (owner/admin/manager/agent/viewer). Found while adding Finance Agent's new
-- finance.* permissions, which got CROSS-JOIN-multiplied across all 69
-- duplicates per role (621 role_permissions rows instead of ~15).
--
-- Safe to re-run: idempotent (no-op once only 1 row per key remains).
BEGIN;

CREATE TEMP TABLE canonical_roles AS
SELECT key, (array_agg(id ORDER BY created_at ASC, id ASC))[1] AS canonical_id
FROM roles WHERE org_id IS NULL GROUP BY key;

-- Repoint user_roles from duplicate role rows to the canonical one. Skip a
-- repoint that would collide with user_roles' PK (user_id, role_id) -- i.e.
-- the user already has the canonical role assigned -- the duplicate row
-- then becomes redundant and is cleaned up by the cascading DELETE below.
UPDATE user_roles ur
SET role_id = cr.canonical_id
FROM roles r
JOIN canonical_roles cr ON cr.key = r.key
WHERE ur.role_id = r.id
  AND r.org_id IS NULL
  AND r.id <> cr.canonical_id
  AND NOT EXISTS (
    SELECT 1 FROM user_roles ur2
    WHERE ur2.user_id = ur.user_id AND ur2.role_id = cr.canonical_id
  );

DELETE FROM roles r
USING canonical_roles cr
WHERE r.key = cr.key AND r.org_id IS NULL AND r.id <> cr.canonical_id;

-- Guard against recurrence: one system role per key, going forward.
CREATE UNIQUE INDEX IF NOT EXISTS idx_roles_system_key_unique ON roles(key) WHERE org_id IS NULL;

COMMIT;
