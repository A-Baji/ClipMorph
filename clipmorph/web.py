"""Local FastAPI service entry point."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import time
from pathlib import Path

from clipmorph.job import default_data_dir
from clipmorph.service import JobService


def create_app(data_dir: str | Path | None = None):
    """Create the local API application without importing web dependencies at CLI startup."""
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as error:
        raise RuntimeError(
            "The web interface requires the optional 'web' dependencies. "
            "Install them with: python -m pip install 'clipmorph[web]'"
        ) from error

    app = FastAPI(title="ClipMorph", version="0.3.0")
    service = JobService(data_dir or default_data_dir())

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/jobs")
    def list_jobs():
        return [asdict(job) for job in service.list_jobs()]

    @app.post("/api/v1/jobs", status_code=202)
    def create_job(payload: dict):
        source_path = payload.get("source_path")
        if not isinstance(source_path, str) or not source_path:
            raise HTTPException(status_code=400, detail="source_path is required")
        configuration = payload.get("configuration", {})
        if not isinstance(configuration, dict):
            raise HTTPException(status_code=400,
                                detail="configuration must be an object")
        try:
            manifest = service.create_job(source_path, configuration)
        except FileNotFoundError as error:
            raise HTTPException(status_code=400,
                                detail=f"source file was not found: {source_path}") from error
        return {"job_id": manifest.job_id, "status_url": f"/api/v1/jobs/{manifest.job_id}"}

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return asdict(service.get_job(job_id))
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, payload: dict | None = None):
        if not payload or payload.get("confirm") is not True:
            raise HTTPException(status_code=400, detail="confirm=true is required")
        try:
            return asdict(service.cancel_job(job_id))
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @app.get("/api/v1/jobs/{job_id}/events")
    def job_events(job_id: str):
        from fastapi.responses import StreamingResponse

        def events():
            while True:
                try:
                    job = service.get_job(job_id)
                except FileNotFoundError:
                    return
                yield f"data: {json.dumps(asdict(job))}\n\n"
                if job.status in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the ClipMorph web service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError(
            "The web interface requires the optional 'web' dependencies. "
            "Install them with: python -m pip install 'clipmorph[web]'"
        ) from error

    uvicorn.run(create_app(), host=args.host, port=args.port)