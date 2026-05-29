from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    service_name = os.getenv("RAILWAY_SERVICE_NAME", "")
    service_name_lower = service_name.lower()
    explicit_role = os.getenv("MATCH_MA_SERVICE_ROLE", "").lower()

    role = explicit_role or _infer_role(service_name_lower)
    print(f"Match-MA Railway start: service={service_name or '<unknown>'} role={role}", flush=True)

    if role == "worker-llm":
        _exec([sys.executable, "-m", "backend.app.worker", "--queue", "llm", "--sleep", "2"])
    if role == "worker-embedding":
        _exec([sys.executable, "-m", "backend.app.worker", "--queue", "embedding", "--sleep", "2"])
    if role == "worker-ocr":
        _exec([sys.executable, "-m", "backend.app.worker", "--queue", "ocr", "--sleep", "2"])

    port = os.getenv("PORT", "8080")
    _exec([
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ])


def _infer_role(service_name_lower: str) -> str:
    # Keep service-name inference as a fallback; Railway variables can set
    # MATCH_MA_SERVICE_ROLE explicitly when config-as-code hides start command.
    if "worker" in service_name_lower and "embedding" in service_name_lower:
        return "worker-embedding"
    if "worker" in service_name_lower and "ocr" in service_name_lower:
        return "worker-ocr"
    if "worker" in service_name_lower and "llm" in service_name_lower:
        return "worker-llm"
    return "api"


def _exec(command: list[str]) -> None:
    print("Executing: " + " ".join(command), flush=True)
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
