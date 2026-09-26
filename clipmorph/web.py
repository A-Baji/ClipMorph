"""Local FastAPI surface for ClipMorph app config, jobs, reviews, and artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
import uuid

from clipmorph.auth import credential_status, load_auth_config, persist_auth_credentials
from clipmorph.configuration import discover_source_names, load_app_configuration
from clipmorph.configuration import save_app_configuration
from clipmorph.job import default_data_dir, resolve_output_dir
from clipmorph.service import JobService

try:
    from fastapi import FastAPI, File, HTTPException, UploadFile
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
except ImportError:
    FastAPI = File = HTTPException = UploadFile = None
    RequestValidationError = None
    FileResponse = JSONResponse = StreamingResponse = None


SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}


def create_app(data_dir: str | Path | None = None,
               app_config_path: str | Path | None = None):
    """Create one app.yml-backed API instance with shared job service behavior."""
    if FastAPI is None:
        raise RuntimeError(
            "The web interface requires optional dependencies. "
            "Install them with: python -m pip install 'clipmorph[web]'"
        )

    from send2trash import send2trash

    root = Path(data_dir or default_data_dir())
    app_path = Path(app_config_path) if app_config_path else root / "app.yml"
    load_auth_config(root)
    service = JobService(root, app_config_path=app_path)
    app = FastAPI(title="ClipMorph", version="0.4.1")
    app.state.job_service = service

    @app.on_event("shutdown")
    def shutdown_service():
        service.close()

    def app_config() -> dict:
        return load_app_configuration(app_path)

    def source_root() -> Path:
        configured = Path(app_config()["source_dir"])
        return (configured if configured.is_absolute() else app_path.parent / configured).resolve()

    def output_root() -> Path:
        return resolve_output_dir(app_config()["output_dir"], root).resolve()

    def fail(status: int, code: str, message: str):
        raise HTTPException(status_code=status,
                            detail={"code": code, "message": message})

    def service_failure(error: Exception):
        message = str(error)
        conflict_terms = ("stale", "conflict", "immutable", "reopen", "review",
                          "artifact", "checkpoint", "source identity")
        status = 409 if any(term in message.lower() for term in conflict_terms) else 422
        fail(status, "conflict" if status == 409 else "invalid_request", message)

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request, error):
        detail = error.detail
        payload = {"error": detail if isinstance(detail, dict) else {
            "code": "http_error", "message": str(detail)}}
        return JSONResponse(status_code=error.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(_request, error):
        return JSONResponse(status_code=422, content={
            "error": {
                "code": "invalid_request",
                "message": "Request validation failed",
                "fields": [{"type": item.get("type"), "location": item.get("loc"),
                            "message": item.get("msg")}
                           for item in error.errors()],
            },
        })

    frontend_dist = Path(__file__).resolve().parent / "web_assets"
    if not frontend_dist.exists():
        frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def dashboard():
            return FileResponse(frontend_dist / "index.html")

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/configuration")
    def get_configuration():
        return {"configuration": app_config(), "credentials": credential_status()}

    @app.put("/api/v1/configuration")
    def put_configuration(payload: dict):
        try:
            save_app_configuration(app_path, payload.get("configuration"))
        except (TypeError, ValueError) as error:
            fail(422, "invalid_configuration", str(error))
        return {"saved": True, "configuration": app_config()}

    @app.get("/api/v1/credentials")
    def get_credentials():
        return {"credentials": credential_status()}

    @app.put("/api/v1/credentials/{platform}")
    def put_credentials(platform: str, payload: dict):
        credentials = payload.get("credentials")
        if not isinstance(credentials, dict) or any(
                not isinstance(value, str) for value in credentials.values()):
            fail(422, "invalid_credentials", "credentials must be a string object")
        try:
            persist_auth_credentials(platform, credentials, root)
        except ValueError as error:
            fail(422, "invalid_credentials", str(error))
        return {"credentials": credential_status()}

    @app.get("/api/v1/sources")
    def list_sources():
        directory = source_root()
        return [{"name": name, "source": name,
                 "size": (directory / name).stat().st_size}
                for name in discover_source_names(directory)]

    @app.post("/api/v1/sources", status_code=201)
    async def upload_source(file: UploadFile = File(...)):
        if not file.filename:
            fail(422, "source_missing", "file name is required")
        basename = Path(file.filename.replace("\\", "/")).name
        if Path(basename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            fail(422, "unsupported_extension", "source extension is not supported")
        contents = await file.read()
        if not contents:
            fail(422, "source_empty", "source must not be empty")
        directory = source_root()
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / basename
        index = 1
        while destination.exists():
            destination = directory / f"{Path(basename).stem}-{index}{Path(basename).suffix}"
            index += 1
        destination.write_bytes(contents)
        return {"name": destination.name, "source": destination.name}

    @app.get("/api/v1/layouts")
    def list_layouts():
        return app_config()["layouts"]

    @app.post("/api/v1/layouts", status_code=201)
    def create_layout(payload: dict):
        name, layout = payload.get("name"), payload.get("layout")
        if not isinstance(name, str) or not name.strip() or not isinstance(layout, dict):
            fail(422, "invalid_layout", "name and layout object are required")
        try:
            from clipmorph.layout import validate_layout
            validate_layout(layout)
        except ValueError as error:
            fail(422, "invalid_layout", str(error))
        record = {"id": uuid.uuid4().hex, "name": name.strip(), "layout": layout}
        config = app_config()
        config["layouts"].append(record)
        save_app_configuration(app_path, config)
        return record

    @app.get("/api/v1/layouts/{layout_id}")
    def get_layout(layout_id: str):
        record = next((item for item in app_config()["layouts"]
                       if item["id"] == layout_id), None)
        if record is None:
            fail(404, "not_found", "layout not found")
        return record

    @app.patch("/api/v1/layouts/{layout_id}")
    def patch_layout(layout_id: str, payload: dict):
        config = app_config()
        found = False
        updated = []
        for record in config["layouts"]:
            if record["id"] != layout_id:
                updated.append(record)
                continue
            found = True
            next_record = dict(record)
            if "name" in payload:
                name = payload["name"]
                if not isinstance(name, str) or not name.strip():
                    fail(422, "invalid_layout", "name must not be empty")
                next_record["name"] = name.strip()
            if "layout" in payload:
                if not isinstance(payload["layout"], dict):
                    fail(422, "invalid_layout", "layout must be an object")
                from clipmorph.layout import validate_layout
                try:
                    validate_layout(payload["layout"])
                except ValueError as error:
                    fail(422, "invalid_layout", str(error))
                next_record["layout"] = payload["layout"]
            updated.append(next_record)
        if not found:
            fail(404, "not_found", "layout not found")
        config["layouts"] = updated
        save_app_configuration(app_path, config)
        return next(item for item in updated if item["id"] == layout_id)

    @app.delete("/api/v1/layouts/{layout_id}")
    def delete_layout(layout_id: str, confirm: bool = False):
        if not confirm:
            fail(400, "confirmation_required", "confirm=true is required")
        config = app_config()
        layouts = config["layouts"]
        config["layouts"] = [item for item in layouts if item["id"] != layout_id]
        if len(config["layouts"]) == len(layouts):
            fail(404, "not_found", "layout not found")
        save_app_configuration(app_path, config)
        return {"deleted": True, "id": layout_id}

    @app.post("/api/v1/jobs/validate")
    def validate_jobs(payload: dict):
        try:
            if "source_names" in payload:
                result = service.create_jobs(
                    payload.get("source_names"), payload.get("job_configs"),
                    config_dir=payload.get("config_dir"),
                    overrides=payload.get("overrides"), dry_run=True)
                return {"valid": not result["failed"], **result, "warnings": []}
            source = payload.get("source")
            if not isinstance(source, str):
                fail(422, "source_required", "source is required")
            _, effective, _ = service.resolve_job(
                source, payload.get("configuration", {}))
            return {"valid": True, "created": [], "skipped": [], "failed": [],
                    "effective_configurations": [{
                        "source": effective["general"]["source"],
                        "configuration": effective}], "warnings": []}
        except FileNotFoundError as error:
            fail(422, "source_missing", str(error))
        except ValueError as error:
            fail(422, "invalid_configuration", str(error))

    @app.post("/api/v1/jobs", status_code=202)
    def create_job(payload: dict):
        source = payload.get("source")
        configuration = payload.get("configuration", {})
        if not isinstance(source, str) or not isinstance(configuration, dict):
            fail(422, "invalid_request", "source and configuration object are required")
        try:
            from clipmorph.workflow import execute_job
            manifest = service.create_job(
                source, configuration,
                lambda job, token: execute_job(
                    job, token, service.jobs_dir, service.app_config_path))
        except (FileNotFoundError, ValueError) as error:
            fail(422, "invalid_job", str(error))
        return {"job_id": manifest.job_id, "job": asdict(manifest),
                "status_url": f"/api/v1/jobs/{manifest.job_id}"}

    @app.post("/api/v1/jobs/bulk")
    def create_jobs(payload: dict):
        try:
            from clipmorph.workflow import execute_job
            result = service.create_jobs(
                source_names=payload.get("source_names"),
                job_configs=payload.get("job_configs"),
                config_dir=payload.get("config_dir"),
                overrides=payload.get("overrides"),
                runner=lambda job, token: execute_job(
                    job, token, service.jobs_dir, service.app_config_path))
        except ValueError as error:
            fail(422, "invalid_request", str(error))
        return JSONResponse(status_code=202 if result["created"] else 200,
                            content=result)

    @app.get("/api/v1/jobs")
    def list_jobs(status: str | None = None):
        jobs = service.list_jobs()
        if status is not None:
            jobs = [item for item in jobs if item.status == status]
        return [asdict(item) for item in jobs]

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return asdict(service.get_job(job_id))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")

    @app.patch("/api/v1/jobs/{job_id}/configuration")
    def patch_job_configuration(job_id: str, payload: dict):
        try:
            result = service.update_job_configuration(
                job_id, payload.get("patch"),
                payload.get("expected_configuration_hash", ""),
                bool(payload.get("reopen", False)))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)
        return asdict(result)

    @app.delete("/api/v1/jobs/{job_id}")
    def delete_job(job_id: str, confirm: bool = False):
        if not confirm:
            fail(400, "confirmation_required", "confirm=true is required")
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        job_dir = service.jobs_dir / job_id
        output_dir = output_root() / job_id
        if job_dir.exists():
            send2trash(str(job_dir))
        if output_dir.exists():
            send2trash(str(output_dir))
        return {"deleted": True, "job_id": manifest.job_id}

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, payload: dict):
        if payload.get("confirm") is not True:
            fail(400, "confirmation_required", "confirm=true is required")
        try:
            return asdict(service.cancel_job(job_id))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")

    @app.post("/api/v1/jobs/{job_id}/resume", status_code=202)
    def resume_job(job_id: str):
        try:
            from clipmorph.workflow import execute_job
            service.resume_job(job_id, lambda job, token: execute_job(
                job, token, service.jobs_dir, service.app_config_path))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)
        return {"job_id": job_id, "status_url": f"/api/v1/jobs/{job_id}"}

    @app.get("/api/v1/jobs/{job_id}/transcript")
    def get_transcript(job_id: str):
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        if not manifest.active_transcript:
            fail(404, "not_found", "transcript not found")
        path = service.jobs_dir / job_id / manifest.active_transcript["path"]
        if not path.is_file():
            fail(404, "not_found", "transcript revision is unavailable")
        from clipmorph.transcript import load_edit_session
        return load_edit_session(path)

    @app.put("/api/v1/jobs/{job_id}/transcript")
    def put_transcript(job_id: str, payload: dict):
        data = dict(payload)
        expected_revision = data.pop("expected_revision", None)
        checkpoint_revision = data.pop("expected_checkpoint_revision", None)
        reopen = bool(data.pop("reopen", False))
        if not isinstance(expected_revision, int):
            fail(422, "revision_required", "expected_revision is required")
        try:
            return service.save_transcript_session(
                job_id, data, expected_revision, checkpoint_revision, reopen)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)

    @app.post("/api/v1/jobs/{job_id}/checkpoints/{stage}/accept")
    def accept_checkpoint(job_id: str, stage: str, payload: dict):
        revision = payload.get("expected_revision")
        if not isinstance(revision, int):
            fail(422, "revision_required", "expected_revision is required")
        try:
            return asdict(service.accept_checkpoint(job_id, stage, revision))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)

    @app.get("/api/v1/jobs/{job_id}/checkpoints/upload")
    def get_upload_draft(job_id: str):
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        return {"upload": manifest.configuration["upload"],
                "checkpoint": manifest.checkpoints["upload"]}

    @app.put("/api/v1/jobs/{job_id}/checkpoints/upload")
    def put_upload_draft(job_id: str, payload: dict):
        revision = payload.get("expected_revision")
        upload = payload.get("upload")
        if not isinstance(revision, int) or not isinstance(upload, dict):
            fail(422, "invalid_request", "expected_revision and upload object are required")
        try:
            manifest = service.update_upload_draft(
                job_id, upload, revision, reopen=bool(payload.get("reopen", False)))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)
        return {"upload": manifest.configuration["upload"],
                "checkpoint": manifest.checkpoints["upload"]}

    @app.delete("/api/v1/jobs/{job_id}/checkpoints/upload")
    def delete_upload_draft(job_id: str, expected_revision: int,
                            reopen: bool = False):
        try:
            manifest = service.delete_upload_draft(job_id, expected_revision, reopen)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)
        return {"upload": manifest.configuration["upload"],
                "checkpoint": manifest.checkpoints["upload"]}

    @app.get("/api/v1/jobs/{job_id}/uploads")
    def list_uploads(job_id: str):
        try:
            return service.get_job(job_id).upload_attempts
        except FileNotFoundError:
            fail(404, "not_found", "job not found")

    @app.post("/api/v1/jobs/{job_id}/upload", status_code=202)
    def submit_upload(job_id: str, payload: dict):
        try:
            return service.submit_upload(
                job_id, payload.get("platforms"), payload.get("artifact_id"),
                bool(payload.get("confirm_historical_artifact", False)))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)

    @app.post("/api/v1/jobs/{job_id}/uploads/{platform}/retry", status_code=202)
    def retry_upload(job_id: str, platform: str, payload: dict):
        try:
            return service.retry_upload(
                job_id, platform, payload.get("attempt_id", ""),
                payload.get("artifact_id"),
                bool(payload.get("confirm_historical_artifact", False)))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)

    @app.post("/api/v1/jobs/{job_id}/checkpoints/{stage}/retry", status_code=202)
    def retry_checkpoint(job_id: str, stage: str, payload: dict):
        revision = payload.get("expected_revision")
        if not isinstance(revision, int):
            fail(422, "revision_required", "expected_revision is required")
        try:
            manifest = service.get_job(job_id)
            checkpoint = manifest.checkpoints[stage]
            manifest.transition_checkpoint(stage, "pending", revision, service.jobs_dir)
            from clipmorph.workflow import execute_job
            service.resume_job(job_id, lambda job, token: execute_job(
                job, token, service.jobs_dir, service.app_config_path))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except (KeyError, ValueError) as error:
            service_failure(error)
        return {"job_id": job_id, "status_url": f"/api/v1/jobs/{job_id}"}

    @app.post("/api/v1/jobs/{job_id}/render", status_code=202)
    def render_job(job_id: str):
        try:
            manifest = service.get_job(job_id)
            checkpoint = manifest.checkpoints["conversion"]
            if checkpoint["status"] == "completed":
                manifest.transition_checkpoint(
                    "conversion", "stale", checkpoint["revision"], service.jobs_dir)
                manifest = service.get_job(job_id)
                checkpoint = manifest.checkpoints["conversion"]
                manifest.transition_checkpoint(
                    "conversion", "pending", checkpoint["revision"], service.jobs_dir)
                manifest = service.get_job(job_id)
                service.get_job(job_id).invalidate_checkpoint(
                    "upload", {"code": "rerender", "message": "Conversion rerendered"},
                    service.jobs_dir)
            elif checkpoint["status"] in {"failed", "cancelled", "stale"}:
                manifest.transition_checkpoint(
                    "conversion", "pending", checkpoint["revision"], service.jobs_dir)
            from clipmorph.workflow import execute_job
            service.resume_job(job_id, lambda job, token: execute_job(
                job, token, service.jobs_dir, service.app_config_path))
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        except ValueError as error:
            service_failure(error)
        return {"job_id": job_id, "status_url": f"/api/v1/jobs/{job_id}"}

    @app.get("/api/v1/jobs/{job_id}/artifacts")
    def list_artifacts(job_id: str):
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        return [{key: value for key, value in item.items() if key != "path"}
                for item in manifest.artifacts.values()]

    @app.get("/api/v1/jobs/{job_id}/artifacts/{artifact_id}")
    def get_artifact(job_id: str, artifact_id: str):
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        artifact = manifest.artifacts.get(artifact_id)
        if artifact is None or artifact.get("state") == "deleted":
            fail(404, "not_found", "artifact not found")
        return {key: value for key, value in artifact.items() if key != "path"}

    def artifact_record(job_id: str, artifact_id: str):
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        artifact = manifest.artifacts.get(artifact_id)
        if artifact is None or artifact.get("state") == "deleted":
            fail(404, "not_found", "artifact not found")
        path = Path(artifact["path"]).resolve()
        job_output = output_root() / job_id
        job_data = service.jobs_dir / job_id
        allowed = [job_output, job_data]
        if artifact.get("kind") == "source":
            allowed.append(source_root())
        if not any(path == root_path or root_path in path.parents for root_path in allowed):
            fail(404, "not_found", "artifact path is outside allowed job roots")
        if not path.is_file():
            fail(404, "not_found", "artifact bytes are unavailable")
        return manifest, artifact, path

    @app.get("/api/v1/jobs/{job_id}/artifacts/{artifact_id}/preview")
    def preview_artifact(job_id: str, artifact_id: str):
        _manifest, artifact, path = artifact_record(job_id, artifact_id)
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/v1/jobs/{job_id}/artifacts/{artifact_id}/download")
    def download_artifact(job_id: str, artifact_id: str):
        _manifest, artifact, path = artifact_record(job_id, artifact_id)
        return FileResponse(path, filename=artifact.get("display_name", path.name))

    @app.patch("/api/v1/jobs/{job_id}/artifacts/{artifact_id}")
    def patch_artifact(job_id: str, artifact_id: str, payload: dict):
        name = payload.get("display_name")
        if (not isinstance(name, str) or not name.strip()
                or "/" in name or "\\" in name):
            fail(422, "invalid_artifact_name", "display_name must be a filename")
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        artifact = manifest.artifacts.get(artifact_id)
        if artifact is None or artifact.get("state") == "deleted":
            fail(404, "not_found", "artifact not found")
        artifact["display_name"] = name.strip()
        manifest.save(service.jobs_dir)
        return {key: value for key, value in artifact.items() if key != "path"}

    @app.delete("/api/v1/jobs/{job_id}/artifacts/{artifact_id}")
    def delete_artifact(job_id: str, artifact_id: str, confirm: bool = False):
        if not confirm:
            fail(400, "confirmation_required", "confirm=true is required")
        try:
            manifest = service.get_job(job_id)
        except FileNotFoundError:
            fail(404, "not_found", "job not found")
        artifact = manifest.artifacts.get(artifact_id)
        if artifact is None or artifact.get("state") == "deleted":
            fail(404, "not_found", "artifact not found")
        if artifact.get("kind") == "source":
            fail(409, "source_immutable", "source artifacts cannot be deleted")
        path = Path(artifact["path"])
        if path.exists():
            send2trash(str(path))
        artifact["state"] = "deleted"
        artifact["deleted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if manifest.current_artifact_id == artifact_id:
            manifest.artifact_path = None
        manifest.save(service.jobs_dir)
        return {"deleted": True, "artifact_id": artifact_id}

    @app.get("/api/v1/jobs/{job_id}/events")
    def job_events(job_id: str):
        def events():
            while True:
                try:
                    manifest = service.get_job(job_id)
                except FileNotFoundError:
                    return
                yield f"data: {json.dumps(asdict(manifest))}\n\n"
                if manifest.status in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.5)
        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the ClipMorph web service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--app-config", type=Path)
    args = parser.parse_args()
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError("Install web dependencies with pip install 'clipmorph[web]'") from error
    uvicorn.run(create_app(args.data_dir, args.app_config),
                host=args.host, port=args.port)