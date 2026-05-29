from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    service_name = os.getenv("RAILWAY_SERVICE_NAME", "")
    role = os.getenv("MATCH_MA_SERVICE_ROLE", "").lower()
    # Railway health checks are configured in railway.toml for the API service.
    # Worker services are deployed with MATCH_MA_SERVICE_ROLE so the same root
    # config can start long-running workers without running migrations.
    is_worker = role.startswith("worker")

    service_label = service_name or "<unknown>"
    role_label = role or "<auto>"
    print(f"Match-MA Railway pre-deploy: service={service_label} role={role_label}", flush=True)

    if is_worker:
        print("Skipping alembic migrations for worker service.", flush=True)
        return

    print("Running alembic migrations for API service.", flush=True)
    raise SystemExit(subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"]))


if __name__ == "__main__":
    main()
