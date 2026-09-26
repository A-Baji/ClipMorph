"""Command-line parsing and shared service command handlers."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
from typing import Any
import uuid
import webbrowser

import yaml

from clipmorph.job import default_data_dir
from clipmorph.platforms import build_platform_default_config


def summarize_runtime_configuration(runtime_values=None):
    defaults = build_platform_default_config()
    for key, value in (runtime_values or {}).items():
        for platform in defaults:
            prefix = f"{platform}_"
            if isinstance(key, str) and key.startswith(prefix):
                defaults[platform][key[len(prefix):]] = value
    return defaults


def _build_command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clipmorph", description="Create and manage ClipMorph jobs.")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--app-config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create app.yml and auth.yaml templates.")
    init.add_argument("--config-path", type=Path)

    web = commands.add_parser("web", help="Start the local API and dashboard.")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8000)

    auth = commands.add_parser("auth", help="Manage platform credentials.")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser("status")
    auth_set = auth_commands.add_parser("set")
    auth_set.add_argument("platform")
    auth_commands.add_parser("twitter")

    job = commands.add_parser("job", help="Create and manage per-source jobs.")
    job_commands = job.add_subparsers(dest="job_command", required=True)
    create = job_commands.add_parser("create")
    create.add_argument("source", type=Path)
    create.add_argument("--job-configs", type=Path)
    create.add_argument("--config-dir", type=Path)
    create.add_argument("--dry-run", action="store_true")
    create.add_argument("--yes", action="store_true")
    listing = job_commands.add_parser("list")
    listing.add_argument("--status")
    get = job_commands.add_parser("get")
    get.add_argument("job_id")
    update = job_commands.add_parser("update")
    update.add_argument("job_id")
    update.add_argument("--patch", type=Path, required=True)
    update.add_argument("--reopen", action="store_true")
    delete = job_commands.add_parser("delete")
    delete.add_argument("job_id")
    delete.add_argument("--yes", action="store_true")
    resume = job_commands.add_parser("resume")
    resume.add_argument("job_id")
    cancel = job_commands.add_parser("cancel")
    cancel.add_argument("job_id")
    cancel.add_argument("--yes", action="store_true")
    review = job_commands.add_parser("review")
    review.add_argument("job_id")
    review.add_argument("checkpoint", choices=["transcript", "conversion", "upload"])
    review.add_argument("--edits", type=Path)
    review.add_argument("--accept", action="store_true")
    review.add_argument("--reopen", action="store_true")
    render = job_commands.add_parser("render")
    render.add_argument("job_id")
    upload = job_commands.add_parser("upload")
    upload.add_argument("upload_args", nargs="+")
    upload.add_argument("--platform", action="append")
    upload.add_argument("--attempt-id")
    upload.add_argument("--artifact-id")
    upload.add_argument("--confirm-historical-artifact", action="store_true")

    artifacts = job_commands.add_parser("artifacts")
    artifact_commands = artifacts.add_subparsers(dest="artifact_command", required=True)
    artifact_list = artifact_commands.add_parser("list")
    artifact_list.add_argument("job_id")
    for name in ("preview", "download", "rename", "delete"):
        command = artifact_commands.add_parser(name)
        command.add_argument("job_id")
        command.add_argument("artifact_id")
        if name == "download":
            command.add_argument("--destination", type=Path, required=True)
        elif name == "rename":
            command.add_argument("--name", required=True)
        elif name == "delete":
            command.add_argument("--yes", action="store_true")

    layout = commands.add_parser("layout", help="Manage the global layout registry.")
    layout_commands = layout.add_subparsers(dest="layout_command", required=True)
    layout_commands.add_parser("list")
    layout_create = layout_commands.add_parser("create")
    layout_create.add_argument("configuration", type=Path)
    layout_get = layout_commands.add_parser("get")
    layout_get.add_argument("layout_id")
    layout_delete = layout_commands.add_parser("delete")
    layout_delete.add_argument("layout_id")
    layout_delete.add_argument("--yes", action="store_true")
    return parser


def _read_structured_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        value = yaml.safe_load(text) if path.suffix.lower() in {".yaml", ".yml"} else json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"Unable to read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str))


def run_cli(argv: list[str] | None = None) -> int:
    """Execute one public command, returning the documented process status."""
    import getpass

    from clipmorph.auth import AUTH_ENVIRONMENT_KEYS
    from clipmorph.auth import create_auth_template
    from clipmorph.auth import credential_status
    from clipmorph.auth import persist_auth_credentials
    from clipmorph.configuration import DEFAULT_APP_CONFIGURATION
    from clipmorph.configuration import load_app_configuration
    from clipmorph.configuration import load_job_records
    from clipmorph.configuration import save_app_configuration
    from clipmorph.service import JobService

    args = _build_command_parser().parse_args(argv)
    data_dir = args.data_dir
    app_config_path = args.app_config or data_dir / "app.yml"
    try:
        if args.command == "init":
            target = args.config_path or app_config_path
            if not target.exists():
                save_app_configuration(target, DEFAULT_APP_CONFIGURATION)
            create_auth_template(target.parent)
            print(f"Initialized {target}")
            return 0

        if args.command == "web":
            import uvicorn
            from clipmorph.web import create_app
            uvicorn.run(create_app(data_dir, app_config_path),
                        host=args.host, port=args.port)
            return 0

        if args.command == "auth":
            if args.auth_command == "status":
                _print_json(credential_status())
                return 0
            if args.auth_command == "twitter":
                from clipmorph.twitter_auth import authorize_twitter
                print(f"Twitter OAuth2 credentials saved to {authorize_twitter(data_dir)}")
                return 0
            fields = AUTH_ENVIRONMENT_KEYS.get(args.platform)
            if fields is None:
                raise ValueError(f"Unsupported auth platform: {args.platform}")
            values = {field: value for field in fields
                      if (value := getpass.getpass(f"{args.platform} {field}: "))}
            if not values:
                raise ValueError("No credential values were entered")
            persist_auth_credentials(args.platform, values, data_dir)
            print(f"Updated {args.platform} credentials")
            return 0

        if args.command == "layout":
            configuration = load_app_configuration(app_config_path)
            layouts = configuration["layouts"]
            if args.layout_command == "list":
                _print_json(layouts)
                return 0
            if args.layout_command == "create":
                layout_spec = _read_structured_file(args.configuration)
                from clipmorph.layout import validate_layout
                name, layout_value = layout_spec.get("name"), layout_spec.get("layout")
                if not isinstance(name, str) or not name.strip() or not isinstance(layout_value, dict):
                    raise ValueError("layout config requires name and layout object")
                validate_layout(layout_value)
                record = {"id": uuid.uuid4().hex, "name": name.strip(),
                          "layout": layout_value}
                configuration["layouts"] = [*layouts, record]
                save_app_configuration(app_config_path, configuration)
                _print_json(record)
                return 0
            if args.layout_command == "get":
                matching = [item for item in layouts
                            if item["id"] == args.layout_id]
                layout_record = matching[0] if matching else None
                if layout_record is None:
                    raise FileNotFoundError("layout not found")
                _print_json(layout_record)
                return 0
            if not args.yes:
                raise ValueError("layout delete requires --yes")
            remaining = [item for item in layouts if item["id"] != args.layout_id]
            if len(remaining) == len(layouts):
                raise FileNotFoundError("layout not found")
            configuration["layouts"] = remaining
            save_app_configuration(app_config_path, configuration)
            return 0

        service = JobService(data_dir, app_config_path=app_config_path)
        try:
            if args.command != "job":
                raise ValueError("unsupported command")
            if args.job_command == "create":
                app_configuration = load_app_configuration(app_config_path)
                source_root = Path(app_configuration["source_dir"])
                if not source_root.is_absolute():
                    source_root = app_config_path.parent / source_root
                if args.source.is_dir():
                    if args.source.resolve() != source_root.resolve():
                        raise ValueError("source directory must match app.yml source_dir")
                    source_names = None
                else:
                    source_names = [args.source.name]
                records = load_job_records(args.job_configs) if args.job_configs else []
                runner = None
                if not args.dry_run:
                    from clipmorph.workflow import execute_job
                    runner = lambda job, token: execute_job(
                        job, token, service.jobs_dir, service.app_config_path)
                result = service.create_jobs(
                    source_names=source_names, job_configs=records,
                    config_dir=args.config_dir, runner=runner, dry_run=args.dry_run)
                _print_json(result)
                return 1 if result["failed"] else 0
            if args.job_command == "list":
                jobs = service.list_jobs()
                if args.status:
                    jobs = [item for item in jobs if item.status == args.status]
                _print_json([asdict(item) for item in jobs])
                return 0
            if args.job_command == "get":
                _print_json(asdict(service.get_job(args.job_id)))
                return 0
            if args.job_command == "update":
                manifest = service.get_job(args.job_id)
                updated = service.update_job_configuration(
                    args.job_id, _read_structured_file(args.patch),
                    manifest.current_configuration_hash, args.reopen)
                _print_json(asdict(updated))
                return 0
            if args.job_command == "delete":
                if not args.yes:
                    raise ValueError("job delete requires --yes")
                manifest = service.get_job(args.job_id)
                from send2trash import send2trash
                job_dir = service.jobs_dir / args.job_id
                if job_dir.exists():
                    send2trash(str(job_dir))
                output_dir = Path(load_app_configuration(app_config_path)["output_dir"])
                if not output_dir.is_absolute():
                    output_dir = app_config_path.parent / output_dir
                output_job = output_dir / args.job_id
                if output_job.exists():
                    send2trash(str(output_job))
                print(manifest.job_id)
                return 0
            if args.job_command == "cancel":
                if not args.yes:
                    raise ValueError("job cancel requires --yes")
                _print_json(asdict(service.cancel_job(args.job_id)))
                return 0
            if args.job_command == "resume":
                from clipmorph.workflow import execute_job
                service.resume_job(args.job_id, lambda job, token: execute_job(
                    job, token, service.jobs_dir, service.app_config_path))
                return 0
            if args.job_command == "review":
                manifest = service.get_job(args.job_id)
                if args.edits:
                    edits = _read_structured_file(args.edits)
                    if args.checkpoint == "transcript":
                        active_revision = (manifest.active_transcript or {}).get("revision", 0)
                        service.save_transcript_session(
                            args.job_id, edits, active_revision,
                            manifest.checkpoints["transcript"]["revision"], args.reopen)
                    elif args.checkpoint == "upload":
                        upload_draft = edits.get("upload", edits)
                        service.update_upload_draft(
                            args.job_id, upload_draft,
                            manifest.checkpoints["upload"]["revision"], args.reopen)
                    elif args.checkpoint == "conversion":
                        patch = edits.get("patch", edits)
                        service.update_job_configuration(
                            args.job_id, patch,
                            manifest.current_configuration_hash, args.reopen)
                    manifest = service.get_job(args.job_id)
                if args.accept:
                    manifest = service.accept_checkpoint(
                        args.job_id, args.checkpoint,
                        manifest.checkpoints[args.checkpoint]["revision"])
                _print_json(asdict(manifest))
                return 0
            if args.job_command == "render":
                manifest = service.get_job(args.job_id)
                checkpoint = manifest.checkpoints["conversion"]
                if checkpoint["status"] in {"failed", "cancelled", "stale"}:
                    manifest.transition_checkpoint(
                        "conversion", "pending", checkpoint["revision"], service.jobs_dir)
                elif checkpoint["status"] == "completed":
                    manifest.transition_checkpoint(
                        "conversion", "stale", checkpoint["revision"], service.jobs_dir)
                    manifest = service.get_job(args.job_id)
                    manifest.transition_checkpoint(
                        "conversion", "pending",
                        manifest.checkpoints["conversion"]["revision"], service.jobs_dir)
                from clipmorph.workflow import execute_job
                service.resume_job(args.job_id, lambda job, token: execute_job(
                    job, token, service.jobs_dir, service.app_config_path))
                return 0
            if args.job_command == "upload":
                if args.upload_args[0] == "retry":
                    if len(args.upload_args) != 3:
                        raise ValueError("syntax: job upload retry ID PLATFORM")
                    _, job_id, platform = args.upload_args
                    manifest = service.get_job(job_id)
                    attempt_id = args.attempt_id
                    if attempt_id is None:
                        attempt = next((item for item in reversed(manifest.upload_attempts)
                                        if item["platform"] == platform
                                        and item["status"] == "failed"), None)
                        if attempt is None:
                            raise ValueError("no failed upload attempt for that platform")
                        attempt_id = attempt["attempt_id"]
                    result = service.retry_upload(
                        job_id, platform, attempt_id, args.artifact_id,
                        args.confirm_historical_artifact)
                else:
                    if len(args.upload_args) != 1:
                        raise ValueError("syntax: job upload ID")
                    result = service.submit_upload(
                        args.upload_args[0], args.platform, args.artifact_id,
                        args.confirm_historical_artifact)
                _print_json(result)
                return 0
            if args.job_command == "artifacts":
                manifest = service.get_job(args.job_id)
                if args.artifact_command == "list":
                    _print_json([{key: value for key, value in item.items() if key != "path"}
                                 for item in manifest.artifacts.values()])
                    return 0
                artifact = manifest.artifacts.get(args.artifact_id)
                if artifact is None:
                    raise FileNotFoundError("artifact not found")
                path = Path(artifact["path"])
                if args.artifact_command == "preview":
                    if not path.is_file():
                        raise FileNotFoundError("artifact bytes are unavailable")
                    webbrowser.open(path.resolve().as_uri())
                    return 0
                if args.artifact_command == "download":
                    shutil.copy2(path, args.destination)
                    print(str(args.destination))
                    return 0
                if args.artifact_command == "rename":
                    if "/" in args.name or "\\" in args.name:
                        raise ValueError("artifact display name must be a filename")
                    artifact["display_name"] = args.name
                    manifest.save(service.jobs_dir)
                    return 0
                if not args.yes:
                    raise ValueError("artifact delete requires --yes")
                from send2trash import send2trash
                if path.exists():
                    send2trash(str(path))
                artifact["state"] = "deleted"
                if manifest.current_artifact_id == args.artifact_id:
                    manifest.artifact_path = None
                manifest.save(service.jobs_dir)
                return 0
            raise ValueError("unsupported job operation")
        finally:
            service.close()
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2