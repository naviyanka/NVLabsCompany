"""Store one secret in the configured secret backend, entered interactively.

    python scripts/store_secret.py REF [--env-file PATH]

The value is read with getpass (no echo, not an argument, never printed). Only
"stored" or "failed" is reported. ``--env-file`` loads settings (SECRET_KEY,
DATABASE_URL) from another checkout's .env, so a worktree without one can be used.
"""

import argparse
import getpass
import sys

from nexus.config import Settings, settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("--env-file")
    args = ap.parse_args()
    if args.env_file:
        for k, v in Settings(_env_file=args.env_file).model_dump().items():
            setattr(settings, k, v)
    from nexus.database import async_session_factory  # imported after settings are final
    from nexus.governance.secret_backend import make_secret_backend

    value = getpass.getpass(f"Value for {args.ref} (hidden): ")
    if not value:
        print("failed: empty")
        return 1
    ok = make_secret_backend(async_session_factory).encrypt(args.ref, value)
    print("stored" if ok else "failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
