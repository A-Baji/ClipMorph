"""Local FastAPI service entry point."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import time
from pathlib import Path

from clipmorph.job import default_data_dir
from clipmorph.service import JobService
from clipmorph.transcript import load_edit_session, save_edit_session
from clipmorph.transcript import validate_edit_session


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
    root = Path(data_dir or default_data_dir())
    service = JobService(root)

    def config_path() -> Path:
        return root / "config.json"

    def mask_configuration(configuration: dict) -> dict:
        masked = {}
        for key, value in configuration.items():
            if any(secret in key.lower() for secret in ("secret", "token", "password", "api_key")):
                masked[key] = "••••••••" if value else ""
            else:
                masked[key] = value
        return masked

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/configuration")
    def get_configuration():
        if not config_path().exists():
            return {"configuration": {}, "credentials": {}}
        configuration = json.loads(config_path().read_text(encoding="utf-8"))
        return {"configuration": mask_configuration(configuration),
                "credentials": {
                    key: bool(value)
                    for key, value in configuration.items()
                    if any(secret in key.lower()
                           for secret in ("secret", "token", "password", "api_key"))
                }}

    @app.put("/api/v1/configuration")
    def save_configuration(payload: dict):
        configuration = payload.get("configuration")
        if not isinstance(configuration, dict):
            raise HTTPException(status_code=422,
                                detail="configuration must be an object")
        existing = {}
        if config_path().exists():
            existing = json.loads(config_path().read_text(encoding="utf-8"))
        for key, value in configuration.items():
            if value != "••••••••":
                existing[key] = value
        root.mkdir(parents=True, exist_ok=True)
        temporary = config_path().with_suffix(".json.tmp")
        temporary.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        temporary.replace(config_path())
        return {"saved": True, "configuration": mask_configuration(existing)}

    @app.get("/api/v1/configuration/export")
    def export_configuration():
        if not config_path().exists():
            return {}
        return json.loads(config_path().read_text(encoding="utf-8"))

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

    @app.get("/api/v1/jobs/{job_id}/artifacts")
    def list_artifacts(job_id: str):
        try:
            return service.get_job(job_id).artifacts
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @app.post("/api/v1/jobs/{job_id}/artifacts/{name}/rename")
    def rename_artifact(job_id: str, name: str, payload: dict):
        if not isinstance(payload.get("name"), str) or not payload["name"]:
            raise HTTPException(status_code=422, detail="name is required")
        try:
            manifest = service.get_job(job_id)
            artifact = manifest.artifacts[name]
            old_path = Path(artifact["path"])
            new_path = old_path.with_name(payload["name"])
            old_path.rename(new_path)
            artifact["path"] = str(new_path)
            manifest.artifact_path = (str(new_path)
                                      if manifest.artifact_path == str(old_path)
                                      else manifest.artifact_path)
            manifest.save(service.jobs_dir)
            return artifact
        except (FileNotFoundError, KeyError) as error:
            raise HTTPException(status_code=404, detail="artifact not found") from error

    @app.delete("/api/v1/jobs/{job_id}/artifacts/{name}")
    def delete_artifact(job_id: str, name: str, confirm: bool = False):
        if not confirm:
            raise HTTPException(status_code=400, detail="confirm=true is required")
        try:
            manifest = service.get_job(job_id)
            artifact = manifest.artifacts.pop(name)
            path = Path(artifact["path"])
            if path.exists():
                from send2trash import send2trash
                send2trash(str(path))
            if manifest.artifact_path == str(path):
                manifest.artifact_path = None
            manifest.save(service.jobs_dir)
            return {"deleted": True, "artifact": name}
        except (FileNotFoundError, KeyError) as error:
            raise HTTPException(status_code=404, detail="artifact not found") from error

    @app.get("/api/v1/jobs/{job_id}/transcript")
    def get_transcript(job_id: str):
        try:
            manifest = service.get_job(job_id)
            path = manifest.artifacts.get("transcript-edited", {}).get("path")
            if not path:
                raise HTTPException(status_code=404, detail="transcript not found")
            return load_edit_session(path)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error

    @app.put("/api/v1/jobs/{job_id}/transcript")
    def save_transcript(job_id: str, payload: dict):
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="job not found") from error
        if payload.get("source_sha256") != manifest.source_sha256:
            raise HTTPException(status_code=409, detail="transcript source does not match job")
        try:
            validate_edit_session(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        path = service.jobs_dir / job_id / "transcript-edited.json"
        save_edit_session(payload, path)
        manifest.record_artifact("transcript-edited", str(path), service.jobs_dir)
        return payload

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