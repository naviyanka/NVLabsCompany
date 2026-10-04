"""The privileged system runtime: the only process that may use the BYPASSRLS role.

Public-facing and ordinary worker processes hold the tenant-bound application role
(``DATABASE_URL``) and nothing else. Work that has to look across tenants (finding which
companies have expired leases, due snapshots or stale runs) runs here, through a fixed
catalogue of operations (:mod:`nexus.system_runtime.ops`). Company-specific changes are
still made through ``tenant_session`` over the application role.

Run it with ``python -m nexus.system_runtime``. See docs/runbooks/system-runtime.md.
"""
