"""Command-line surface: typer application, rich rendering, and command handlers.

``run_cli`` stays the public entry point and keeps the documented process
statuses: ``0`` success, ``1`` a source/runtime failure, ``2`` a usage or
configuration failure, and ``130`` an interruption. Human output is rendered
with rich, which mutes colour on its own when stdout is not a terminal. Every
command that used to print JSON keeps a ``--json`` flag that reproduces the
previous payload unchanged, so machine consumers pass ``--json`` explicitly.

Per-platform upload defaults are owned by ``clipmorph.platforms`` and surface
here only as the runtime summary; how ``upload.content`` becomes a platform
payload belongs to ``clipmorph.policy``.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
import getpass
import json
from pathlib import Path
import shutil
import sys
from typing import Annotated, Any, Literal, Optional
import uuid
import webbrowser

try:  # typer 0.27+ vendors click inside typer._click and drops the dependency.
    import typer._click as typer_click  # type: ignore[import-not-found]
    if not hasattr(typer_click, "Choice"):  # the vendored click is trimmed.
        from typer._types import TyperChoice as _TyperChoice

        typer_click.Choice = _TyperChoice  # type: ignore[attr-defined]
except ImportError:  # typer < 0.27 depends on the standalone click package.
    import click as typer_click  # type: ignore[no-redef]


from rich.box import ASCII2, Box, HEAVY_HEAD
from rich.console import Console
from rich.table import Table
from rich.text import Text
import typer
import yaml
# run_cli maps the exception tree the installed typer actually raises. 0.27
# detached typer.Exit/Abort onto its own RuntimeError classes and its vendored
# exceptions module lost the click Exit/Abort exports, so resolve both sides.
_USAGE_ERROR = typer_click.exceptions.UsageError
_CLICK_EXCEPTION = typer_click.exceptions.ClickException
_EXIT_ERRORS: tuple[type[BaseException], ...] = (typer.Exit,)
_ABORT_ERRORS: tuple[type[BaseException], ...] = (typer.Abort,)
if hasattr(typer_click.exceptions, "Exit"):
    _EXIT_ERRORS += (typer_click.exceptions.Exit,)
if hasattr(typer_click.exceptions, "Abort"):
    _ABORT_ERRORS += (typer_click.exceptions.Abort,)

from clipmorph.job import default_data_dir
from clipmorph.platforms import build_platform_default_config
from clipmorph.platforms import SUPPORTED_PLATFORMS

PROG_NAME = "clipmorph"

# argparse also answered ``-h``, so both spellings are offered on every command.
HELP_CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

# The three manifest checkpoints, in pipeline order.
CHECKPOINT_STAGES = ("transcript", "conversion", "upload")

# Severity colours per status word. rich drops colour on non-terminal stdout,
# so these only add emphasis for humans and never change machine output.
STATUS_STYLES = {
    "completed": "green", "published": "green", "created": "green",
    "ok": "green", "succeeded": "green", "current": "green",
    "running": "cyan", "queued": "cyan", "scheduled": "yellow",
    "awaiting_review": "yellow", "partial_failure": "red", "failed": "red",
    "creation_failed": "red", "invalid_config": "red", "invalid_record": "red",
    "stale": "yellow", "cancelled": "magenta", "skipped": "dim",
    "pending": "dim", "superseded": "dim", "deleted": "dim",
    "validated": "green",
}

# Global options are declared once here and reused by every command so the
# accepted flag names, help text, and positions stay a single source of truth.
DataDirOption = Annotated[
    Optional[Path], typer.Option(
        "--data-dir", help="ClipMorph data directory; defaults to the platform "
        "ClipMorph directory.")]
AppConfigOption = Annotated[
    Optional[Path], typer.Option(
        "--app-config", help="App configuration file; defaults to "
        "<data-dir>/app.yml.")]
JsonOption = Annotated[
    bool, typer.Option(
        "--json", help="Print the machine-readable JSON payload instead of the "
        "rendered table.")]


def summarize_runtime_configuration(runtime_values=None):
    defaults = build_platform_default_config()
    for key, value in (runtime_values or {}).items():
        for platform in defaults:
            prefix = f"{platform}_"
            if isinstance(key, str) and key.startswith(prefix):
                defaults[platform][key[len(prefix):]] = value
    return defaults


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


def _console() -> Console:
    """Return a console for the current stdout.

    One console per render keeps redirected or patched ``sys.stdout``
    authoritative; rich strips markup tags and colour when the stream is not a
    terminal, which is what mutes the human view for pipes and log files.
    """
    return Console(highlight=False)


def _table_box(console: Console) -> Box:
    """Pick the grid style for one render.

    rich's default grid is the heavy unicode box, but ``safe_box`` swaps in a
    different unicode grid on some platforms (light box on legacy Windows
    consoles, heavy box elsewhere), so the same piped output is not identical
    on every OS. Pipes, log files, and captured output get a plain ASCII grid
    everywhere; only a real terminal sees the unicode box. That grid is
    ``ASCII2``, not ``ASCII``: rich's ``ASCII`` box draws continuous top and
    bottom edges without the internal column dividers.
    """
    return HEAVY_HEAD if console.is_terminal else ASCII2


def _tolerate_unencodable_output() -> None:
    """Let redirected streams replace characters they cannot encode.

    Human tables print raw path and title characters. A redirected stdout uses
    the locale encoding, so a cp1252 pipe meeting a CJK or emoji title would
    abort the command with ``UnicodeEncodeError`` after half the table printed.
    Reconfigure in place so escaping never costs the command its exit code;
    the ``--json`` payloads stay ASCII regardless because ``json.dumps``
    escapes non-ASCII by default.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None)
        if not encoding or encoding.lower().replace("-", "") == "utf8":
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):  # pragma: no cover - exotic streams
            pass  # the stream keeps its current behaviour; nothing to escape


def _cell(value: Any, style: str = "") -> Text:
    """Format one value as text rich never re-reads as markup."""
    if isinstance(value, Text):
        return value
    if value is None:
        return Text("-", style=style or "dim")
    if isinstance(value, bool):
        return Text("yes" if value else "no", style=style)
    if isinstance(value, (list, tuple, dict)):
        return Text(json.dumps(value, default=str, sort_keys=True), style=style)
    return Text(str(value), style=style)


def _status(value: Any) -> Text:
    """Format a status word with its severity colour."""
    word = str(value)
    return _cell(word, STATUS_STYLES.get(word, ""))


def _column_label(column: str) -> str:
    return column.replace("_", " ").capitalize()


def _print_table(title: str, rows: list[dict[str, Any]], columns: list[str],
                 nowrap: tuple[str, ...] = ()) -> None:
    """Render one row per record, with a column per requested key.

    Values fold onto the next line instead of being dropped, and identifier
    columns stay on one line so a copied job or artifact ID is never mangled.
    The title is wrapped as text too, so user data embedded in it (a layout
    name, for example) is never read as rich markup.
    """
    console = _console()
    table = Table(title=_cell(title), title_justify="left", header_style="bold",
                   box=_table_box(console))
    for column in columns:
        table.add_column(_column_label(column), overflow="fold",
                         no_wrap=column in nowrap)
    for row in rows:
        table.add_row(*[_cell(row.get(column)) for column in columns])
    console.print(table)
    if not rows:
        console.print(Text("(no entries)", style="dim"))


def _print_fields(title: str, fields: list[tuple[str, Any]]) -> None:
    """Render a labelled record as a key/value grid."""
    _print_table(title, [{"Field": label, "Value": value} for label, value in fields],
                 ["Field", "Value"])


def _print_summary(lines: list[str]) -> None:
    """Print plain result lines through the same console as the tables."""
    console = _console()
    for line in lines:
        console.print(_cell(line))


def _yes_no(value: Any) -> str:
    return "yes" if value else "no"


def _short_hash(value: Any) -> Any:
    return value[:12] if isinstance(value, str) and value else value


def _checkpoint_summary(record: dict[str, Any]) -> Text:
    """Summarize every checkpoint as ``stage=status`` pairs."""
    checkpoints = record.get("checkpoints") or {}
    text = Text(" ")
    for index, stage in enumerate(CHECKPOINT_STAGES):
        if index:
            text.append("  ")
        status = str((checkpoints.get(stage) or {}).get("status", "-"))
        text.append(f"{stage}=", style="dim")
        text.append(status, style=STATUS_STYLES.get(status, ""))
    return text


def _platform_summary(platforms: dict[str, Any]) -> Text:
    """Summarize recorded per-platform results as ``platform=state`` pairs."""
    if not platforms:
        return _cell(None)
    text = Text(" ")
    for index, (platform, result) in enumerate(sorted(platforms.items())):
        if index:
            text.append("  ")
        succeeded = bool(result.get("success")) if isinstance(result, dict) else False
        text.append(f"{platform}=", style="dim")
        text.append("ok" if succeeded else "failed",
                    style="green" if succeeded else "red")
    return text


def _current_checkpoint(record: dict[str, Any]) -> Text:
    """Summarize the checkpoint a job is currently at, with its status."""
    stage = record.get("current_checkpoint")
    if not stage:
        return _cell("complete", "green")
    status = str((record.get("checkpoints") or {}).get(stage, {}).get("status", "-"))
    text = Text(f"{stage} ")
    text.append(status, style=STATUS_STYLES.get(status, ""))
    return text


def _job_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        content = ((record.get("configuration") or {}).get("upload") or {}).get("content") or {}
        rows.append({
            "job_id": record.get("job_id"),
            "source": (record.get("configuration") or {}).get("general", {}).get("source")
            or Path(record.get("source_path") or "").name,
            "title": content.get("title") or None,
            "status": _status(record.get("status")),
            "checkpoint": _current_checkpoint(record),
        })
    return rows


def _job_fields(record: dict[str, Any]) -> list[tuple[str, Any]]:
    """Build the key/value grid shown for one job."""
    artifacts = record.get("artifacts") or {}
    fields: list[tuple[str, Any]] = [
        ("Job ID", record.get("job_id")),
        ("Source", (record.get("configuration") or {}).get("general", {}).get("source")),
        ("Source path", record.get("source_path")),
        ("Title", ((record.get("configuration") or {}).get("upload") or {})
         .get("content", {}).get("title") or None),
        ("Status", _status(record.get("status"))),
        ("Checkpoint", record.get("current_checkpoint")),
        ("Checkpoints", _checkpoint_summary(record)),
        ("Artifacts", f"{len(artifacts)} registered"
         + (f", current {record['current_artifact_id']}"
            if record.get("current_artifact_id") else "")),
        ("Platforms", _platform_summary(record.get("platforms") or {})),
        ("Configuration hash", _short_hash(record.get("current_configuration_hash"))),
        ("Updated at", record.get("updated_at")),
    ]
    warnings = record.get("warnings") or []
    if warnings:
        fields.append(("Warnings", _cell(
            "; ".join(str(item) for item in warnings), "yellow")))
    platform_errors = [f"{platform}: {result.get('error')}"
                       for platform, result in sorted((record.get("platforms") or {}).items())
                       if isinstance(result, dict) and not result.get("success")]
    if platform_errors:
        fields.append(("Platform errors", _cell("; ".join(platform_errors), "red")))
    errors = [error for error in (record.get("errors") or [])
              if isinstance(error, dict)]
    if errors:
        fields.append(("Errors", _cell("; ".join(
            f"{error.get('code', 'error')}: {error.get('message', '')}"
            for error in errors), "red")))
    return fields


def _crop_summary(crop: dict[str, Any]) -> str:
    if not crop.get("enabled"):
        return "disabled"
    composition = crop.get("composition") or {}
    sizing = crop.get("sizing") or {}
    return " ".join(part for part in (
        "enabled",
        str(composition.get("mode") or "overlay"),
        f"placement={composition['placement']}" if composition.get("placement") else "",
        f"mode={sizing['mode']}" if sizing.get("mode") else "",
    ) if part)


def _captions_summary(captions: dict[str, Any]) -> str:
    parts = [f"{section}={len(captions[section]['items'])} items"
             for section in ("overlay", "stacked")
             if isinstance(captions.get(section), dict)
             and captions[section].get("items")]
    return " ".join(parts) or "none"


def _layout_rows(layouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "id": record.get("id"),
        "name": record.get("name"),
        "crop": _crop_summary((record.get("layout") or {}).get("crop") or {}),
        "captions": _captions_summary((record.get("layout") or {}).get("captions") or {}),
    } for record in layouts]


def _print_creation_result(result: dict[str, Any], json_output: bool) -> None:
    """Render a fan-out result as one outcome row per source plus counts."""
    if json_output:
        _print_json(result)
        return
    outcomes = [*(result.get("created") or []), *(result.get("skipped") or []),
                *(result.get("failed") or [])]
    _print_table("Sources", [{
        "source": item.get("source"),
        "status": _status(item.get("status")),
        "code": item.get("code"),
        "message": item.get("message"),
        "job_id": item.get("job_id"),
    } for item in outcomes], ["source", "status", "code", "message", "job_id"],
        nowrap=("job_id",))
    summary = result.get("summary") or {}
    _print_summary([f"created: {summary.get('created', 0)}",
                    f"skipped: {summary.get('skipped', 0)}",
                    f"failed: {summary.get('failed', 0)}",
                    f"total: {summary.get('total', 0)}"])


def _print_upload_result(result: dict[str, Any], json_output: bool) -> None:
    """Render an accepted submission or retry as attempt rows plus a summary."""
    if json_output:
        _print_json(result)
        return
    _print_table("Upload attempts", [{
        "platform": attempt.get("platform"),
        "attempt_id": attempt.get("attempt_id"),
        "status": _status(attempt.get("status")),
        "scheduled_publish_at": attempt.get("scheduled_publish_at"),
    } for attempt in (result.get("attempts") or [])],
        ["platform", "attempt_id", "status", "scheduled_publish_at"],
        nowrap=("attempt_id",))
    _print_summary([f"job: {result.get('job_id')}",
                    f"scheduled: {_yes_no(result.get('scheduled'))}",
                    f"status_url: {result.get('status_url')}"])


@dataclass(frozen=True)
class _GlobalOptions:
    """Global options collected by the root callback for subcommands."""

    data_dir: Path | None = None
    app_config: Path | None = None


def _resolve_paths(ctx: typer.Context, data_dir: Path | None,
                   app_config: Path | None) -> tuple[Path, Path]:
    """Return the data directory and app.yml path selected for one command.

    Global options are accepted both before and after the subcommand, so a
    value given on the command itself wins over the inherited one.
    """
    inherited = ctx.obj if isinstance(ctx.obj, _GlobalOptions) else _GlobalOptions()
    selected_data_dir = Path(data_dir or inherited.data_dir or default_data_dir())
    selected_config = app_config or inherited.app_config
    return (selected_data_dir,
            Path(selected_config) if selected_config else selected_data_dir / "app.yml")


app = typer.Typer(add_completion=False, no_args_is_help=False,
                  context_settings=HELP_CONTEXT_SETTINGS,
                  help="Create and manage ClipMorph jobs.")
auth_app = typer.Typer(no_args_is_help=False, context_settings=HELP_CONTEXT_SETTINGS,
                       help="Manage platform credentials.")
job_app = typer.Typer(no_args_is_help=False,
                      context_settings=HELP_CONTEXT_SETTINGS,
                      help="Create and manage per-source jobs.")
artifact_app = typer.Typer(no_args_is_help=False,
                           context_settings=HELP_CONTEXT_SETTINGS,
                           help="Manage registered artifact revisions.")
layout_app = typer.Typer(no_args_is_help=False,
                         context_settings=HELP_CONTEXT_SETTINGS,
                         help="Manage the global layout registry.")


def _registered_artifact(manifest: Any, artifact_id: str) -> dict[str, Any]:
    """Return one registered artifact record or report a missing one."""
    artifact = manifest.artifacts.get(artifact_id)
    if artifact is None:
        raise FileNotFoundError("artifact not found")
    return artifact


def _artifact_path(ctx: typer.Context, job_id: str, artifact_id: str,
                   data_dir: Path | None, app_config: Path | None) -> Path:
    """Return the local path of one registered artifact."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        manifest = service.get_job(job_id)
        artifact = _registered_artifact(manifest, artifact_id)
        return service.artifact_path(artifact)


@app.callback()
def main_callback(ctx: typer.Context, data_dir: DataDirOption = None,
                  app_config: AppConfigOption = None) -> None:
    """Create and manage ClipMorph jobs."""
    ctx.obj = _GlobalOptions(data_dir=data_dir, app_config=app_config)


@app.command("init")
def init_command(
        ctx: typer.Context,
        config_path: Annotated[Optional[Path], typer.Option(
            "--config-path", help="Write the app configuration template here.")] = None,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Create app.yml and auth.yaml templates."""
    from clipmorph.auth import create_auth_template
    from clipmorph.configuration import DEFAULT_APP_CONFIGURATION
    from clipmorph.configuration import save_app_configuration

    _, selected_config = _resolve_paths(ctx, data_dir, app_config)
    target = config_path or selected_config
    if not target.exists():
        save_app_configuration(target, DEFAULT_APP_CONFIGURATION)
    create_auth_template(target.parent)
    _print_summary([f"Initialized {target}"])


@app.command("web")
def web_command(
        ctx: typer.Context,
        host: Annotated[str, typer.Option(
            "--host", help="Interface the local service binds to.")] = "127.0.0.1",
        port: Annotated[int, typer.Option(
            "--port", help="Port the local service binds to.")] = 8000,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Start the local API and dashboard."""
    import uvicorn

    from clipmorph.web import create_app

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    uvicorn.run(create_app(selected_data_dir, selected_config), host=host, port=port)


@app.command("doctor")
def doctor_command(
        ctx: typer.Context,
        json_output: JsonOption = False,
        source: Annotated[Optional[Path], typer.Option(
            "--source", help="Also probe this source file's media streams.")] = None,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Check the local environment health without writing any state."""
    from clipmorph.doctor import _print_text_report, run_checks

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    checks = run_checks(selected_data_dir, selected_config, source)
    if json_output:
        _print_json({"checks": checks})
    else:
        _print_text_report(checks)
    if any(check["status"] == "failed" for check in checks):
        raise typer.Exit(1)


@auth_app.command("status")
def auth_status_command(
        ctx: typer.Context,
        json_output: JsonOption = False,
        probe: Annotated[bool, typer.Option(
            "--probe", help="Probe configured credentials over the network with "
            "one read-only call per platform; prints the verdict as JSON. "
            "Exits 1 when any probe fails.")] = False,
        platforms: Annotated[Optional[list[str]], typer.Argument(
            help="Platforms to probe; accepts any supported platform plus "
            "hugging_face. Omit to probe every known provider.",
            click_type=typer_click.Choice(
                [*SUPPORTED_PLATFORMS, "hugging_face"]))] = None,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Show which platforms have at least one configured credential."""
    from clipmorph.auth import credential_status, load_auth_config

    selected_data_dir, _ = _resolve_paths(ctx, data_dir, app_config)
    if not probe:
        status = credential_status()
        if json_output:
            _print_json(status)
            return
        _print_table("Credentials",
                     [{"platform": platform, "configured": _cell(value)}
                      for platform, value in status.items()],
                     ["platform", "configured"])
        return
    load_auth_config(selected_data_dir)
    from clipmorph.auth_probe import probe_credentials
    selected = (list(platforms) if platforms
                else [*SUPPORTED_PLATFORMS, "hugging_face"])
    result = probe_credentials(selected)
    _print_json(result)
    if any(entry["probe"] == "failed" for entry in result.values()):
        raise typer.Exit(1)


@auth_app.command("set")
def auth_set_command(
        ctx: typer.Context,
        platform: Annotated[str, typer.Argument(
            help="Platform whose credentials are updated.")],
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Prompt for platform credentials and store them in auth.yaml."""
    from clipmorph.auth import AUTH_ENVIRONMENT_KEYS
    from clipmorph.auth import persist_auth_credentials

    selected_data_dir, _ = _resolve_paths(ctx, data_dir, app_config)
    fields = AUTH_ENVIRONMENT_KEYS.get(platform)
    if fields is None:
        raise ValueError(f"Unsupported auth platform: {platform}")
    values = {field: value for field in fields
              if (value := getpass.getpass(f"{platform} {field}: "))}
    if not values:
        raise ValueError("No credential values were entered")
    persist_auth_credentials(platform, values, selected_data_dir)
    _print_summary([f"Updated {platform} credentials"])


@auth_app.command("twitter")
def auth_twitter_command(ctx: typer.Context, data_dir: DataDirOption = None,
                         app_config: AppConfigOption = None) -> None:
    """Run the existing Twitter/X OAuth2 authorization flow."""
    from clipmorph.twitter_auth import authorize_twitter

    selected_data_dir, _ = _resolve_paths(ctx, data_dir, app_config)
    saved_to = authorize_twitter(selected_data_dir)
    _print_summary([f"Twitter OAuth2 credentials saved to {saved_to}"])


@layout_app.command("list")
def layout_list_command(ctx: typer.Context, json_output: JsonOption = False,
                        data_dir: DataDirOption = None,
                        app_config: AppConfigOption = None) -> None:
    """List the global layout registry."""
    from clipmorph.configuration import load_app_configuration

    _, selected_config = _resolve_paths(ctx, data_dir, app_config)
    layouts = load_app_configuration(selected_config)["layouts"]
    if json_output:
        _print_json(layouts)
        return
    _print_table("Layouts", _layout_rows(layouts), ["id", "name", "crop", "captions"])


@layout_app.command("create")
def layout_create_command(
        ctx: typer.Context,
        configuration: Annotated[Path, typer.Argument(
            help="YAML/JSON file holding a name and layout object.")],
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Register a layout from a YAML/JSON file."""
    from clipmorph.configuration import load_app_configuration
    from clipmorph.configuration import save_app_configuration
    from clipmorph.layout import validate_layout

    _, selected_config = _resolve_paths(ctx, data_dir, app_config)
    app_configuration = load_app_configuration(selected_config)
    layout_spec = _read_structured_file(configuration)
    name, layout_value = layout_spec.get("name"), layout_spec.get("layout")
    if not isinstance(name, str) or not name.strip() or not isinstance(layout_value, dict):
        raise ValueError("layout config requires name and layout object")
    validate_layout(layout_value)
    record = {"id": uuid.uuid4().hex, "name": name.strip(), "layout": layout_value}
    app_configuration["layouts"] = [*app_configuration["layouts"], record]
    save_app_configuration(selected_config, app_configuration)
    if json_output:
        _print_json(record)
        return
    _print_fields(f"Layout {record['name']}", [("id", record["id"]),
                                               ("name", record["name"]),
                                               ("layout", record["layout"])])


@layout_app.command("get")
def layout_get_command(
        ctx: typer.Context,
        layout_id: Annotated[str, typer.Argument(help="Registry layout ID.")],
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Show one registry layout."""
    from clipmorph.configuration import load_app_configuration

    _, selected_config = _resolve_paths(ctx, data_dir, app_config)
    layouts = load_app_configuration(selected_config)["layouts"]
    matching = [item for item in layouts if item["id"] == layout_id]
    if not matching:
        raise FileNotFoundError("layout not found")
    record = matching[0]
    if json_output:
        _print_json(record)
        return
    _print_fields(f"Layout {record.get('name')}", [("id", record.get("id")),
                                                    ("name", record.get("name")),
                                                    ("layout", record.get("layout"))])


@layout_app.command("delete")
def layout_delete_command(
        ctx: typer.Context,
        layout_id: Annotated[str, typer.Argument(help="Registry layout ID.")],
        yes: Annotated[bool, typer.Option(
            "--yes", help="Confirm the deletion.")] = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Delete one registry layout."""
    from clipmorph.configuration import load_app_configuration
    from clipmorph.configuration import save_app_configuration

    _, selected_config = _resolve_paths(ctx, data_dir, app_config)
    app_configuration = load_app_configuration(selected_config)
    if not yes:
        raise ValueError("layout delete requires --yes")
    layouts = app_configuration["layouts"]
    remaining = [item for item in layouts if item["id"] != layout_id]
    if len(remaining) == len(layouts):
        raise FileNotFoundError("layout not found")
    app_configuration["layouts"] = remaining
    save_app_configuration(selected_config, app_configuration)


@job_app.command("create")
def job_create_command(
        ctx: typer.Context,
        source: Annotated[Path, typer.Argument(
            help="Source file, or the source_dir itself to fan out over it.")],
        job_configs: Annotated[Optional[Path], typer.Option(
            "--job-configs", help="JSONL or YAML per-source job records.")] = None,
        config_dir: Annotated[Optional[Path], typer.Option(
            "--config-dir", help="Directory holding per-source sidecars.")] = None,
        dry_run: Annotated[bool, typer.Option(
            "--dry-run", help="Validate sources and configuration without "
            "writing jobs or manifests.")] = False,
        yes: Annotated[bool, typer.Option(
            "--yes", help="Accept confirmations; job creation never prompts.")] = False,
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Create one job, or fan out over every source in the source directory."""
    from clipmorph.configuration import load_app_configuration
    from clipmorph.configuration import load_job_records
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        app_configuration = load_app_configuration(selected_config)
        source_root = Path(app_configuration["source_dir"])
        if not source_root.is_absolute():
            source_root = selected_config.parent / source_root
        if source.is_dir():
            if source.resolve() != source_root.resolve():
                raise ValueError("source directory must match app.yml source_dir")
            source_names = None
        else:
            source_names = [source.name]
        records = load_job_records(job_configs) if job_configs else []
        runner = None
        if not dry_run:
            from clipmorph.workflow import execute_job
            runner = lambda job, token: execute_job(
                job, token, service.jobs_dir, service.app_config_path)
        result = service.create_jobs(
            source_names=source_names, job_configs=records,
            config_dir=config_dir, runner=runner, dry_run=dry_run)
    _print_creation_result(result, json_output)
    if result["failed"]:
        raise typer.Exit(1)


@job_app.command("list")
def job_list_command(
        ctx: typer.Context,
        status: Annotated[Optional[str], typer.Option(
            "--status", help="Keep only jobs in this status.")] = None,
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """List jobs with their status, title, and current checkpoint."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        jobs = service.list_jobs()
    if status:
        jobs = [item for item in jobs if item.status == status]
    records = [asdict(item) for item in jobs]
    if json_output:
        _print_json(records)
        return
    _print_table("Jobs", _job_rows(records),
                 ["job_id", "source", "title", "status", "checkpoint"],
                 nowrap=("job_id",))


@job_app.command("get")
def job_get_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Show one job manifest with its checkpoints, artifacts, and platforms."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        record = asdict(service.get_job(job_id))
    if json_output:
        _print_json(record)
        return
    _print_fields(f"Job {job_id}", _job_fields(record))


@job_app.command("update")
def job_update_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        patch: Annotated[Path, typer.Option(
            "--patch", help="YAML/JSON per-job configuration patch.")],
        reopen: Annotated[bool, typer.Option(
            "--reopen", help="Reopen completed work for the changed inputs.")] = False,
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Apply a validated per-job configuration patch against the current hash."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        manifest = service.get_job(job_id)
        updated = service.update_job_configuration(
            job_id, _read_structured_file(patch),
            manifest.current_configuration_hash, reopen)
    record = asdict(updated)
    if json_output:
        _print_json(record)
        return
    _print_fields(f"Job {job_id}", _job_fields(record))


@job_app.command("delete")
def job_delete_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        yes: Annotated[bool, typer.Option(
            "--yes", help="Confirm the deletion.")] = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Trash a job's local directory and output."""
    from send2trash import send2trash

    from clipmorph.configuration import load_app_configuration
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        if not yes:
            raise ValueError("job delete requires --yes")
        manifest = service.get_job(job_id)
        job_dir = service.jobs_dir / job_id
        if job_dir.exists():
            send2trash(str(job_dir))
        output_dir = Path(load_app_configuration(selected_config)["output_dir"])
        if not output_dir.is_absolute():
            output_dir = selected_config.parent / output_dir
        output_job = output_dir / job_id
        if output_job.exists():
            send2trash(str(output_job))
    _print_summary([manifest.job_id])


@job_app.command("cancel")
def job_cancel_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        yes: Annotated[bool, typer.Option(
            "--yes", help="Confirm the cancellation.")] = False,
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Cancel queued or running work for a job."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        if not yes:
            raise ValueError("job cancel requires --yes")
        record = asdict(service.cancel_job(job_id))
    if json_output:
        _print_json(record)
        return
    _print_fields(f"Job {job_id}", _job_fields(record))


@job_app.command("resume")
def job_resume_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Resume the next executable checkpoint of a job."""
    from clipmorph.service import JobService
    from clipmorph.workflow import execute_job

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        service.resume_job(job_id, lambda job, token: execute_job(
            job, token, service.jobs_dir, service.app_config_path))


@job_app.command("review")
def job_review_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        checkpoint: Annotated[Literal["transcript", "conversion", "upload"],
                              typer.Argument(help="Checkpoint to review.")],
        edits: Annotated[Optional[Path], typer.Option(
            "--edits", help="YAML/JSON edit object for the checkpoint.")] = None,
        accept: Annotated[bool, typer.Option(
            "--accept", help="Accept the current checkpoint revision.")] = False,
        reopen: Annotated[bool, typer.Option(
            "--reopen", help="Reopen the checkpoint for the changed inputs.")] = False,
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Apply checkpoint edits and optionally accept the review gate."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        manifest = service.get_job(job_id)
        if edits:
            edit_values = _read_structured_file(edits)
            if checkpoint == "transcript":
                active_revision = (manifest.active_transcript or {}).get("revision", 0)
                service.save_transcript_session(
                    job_id, edit_values, active_revision,
                    manifest.checkpoints["transcript"]["revision"], reopen)
            elif checkpoint == "upload":
                upload_draft = edit_values.get("upload", edit_values)
                service.update_upload_draft(
                    job_id, upload_draft,
                    manifest.checkpoints["upload"]["revision"], reopen)
            elif checkpoint == "conversion":
                service.update_job_configuration(
                    job_id, edit_values.get("patch", edit_values),
                    manifest.current_configuration_hash, reopen)
            manifest = service.get_job(job_id)
        if accept:
            manifest = service.accept_checkpoint(
                job_id, checkpoint, manifest.checkpoints[checkpoint]["revision"])
    record = asdict(manifest)
    if json_output:
        _print_json(record)
        return
    _print_fields(f"Job {job_id}", _job_fields(record))


@job_app.command("render")
def job_render_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Rerender the accepted composition as a new immutable artifact."""
    from clipmorph.service import JobService
    from clipmorph.workflow import execute_job

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        manifest = service.get_job(job_id)
        conversion = manifest.checkpoints["conversion"]
        if conversion["status"] in {"failed", "cancelled", "stale"}:
            manifest.transition_checkpoint(
                "conversion", "pending", conversion["revision"], service.jobs_dir)
        elif conversion["status"] == "completed":
            manifest.transition_checkpoint(
                "conversion", "stale", conversion["revision"], service.jobs_dir)
            manifest = service.get_job(job_id)
            manifest.transition_checkpoint(
                "conversion", "pending",
                manifest.checkpoints["conversion"]["revision"], service.jobs_dir)
        service.resume_job(job_id, lambda job, token: execute_job(
            job, token, service.jobs_dir, service.app_config_path))


@job_app.command("upload")
def job_upload_command(
        ctx: typer.Context,
        upload_args: Annotated[Optional[list[str]], typer.Argument(
            metavar="ID | RETRY ID PLATFORM",
            help="Job ID, or retry with a job ID and platform.")] = None,
        platform: Annotated[Optional[list[str]], typer.Option(
            "--platform", help="Limit the submission to this platform; repeatable."
        )] = None,
        attempt_id: Annotated[Optional[str], typer.Option(
            "--attempt-id", help="Failed attempt ID to retry.")] = None,
        artifact_id: Annotated[Optional[str], typer.Option(
            "--artifact-id", help="Artifact ID for a historical retry.")] = None,
        confirm_historical_artifact: Annotated[bool, typer.Option(
            "--confirm-historical-artifact",
            help="Confirm retrying an artifact other than the current one.")] = False,
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Submit the accepted upload draft, or retry one failed attempt."""
    from clipmorph.service import JobService

    if not upload_args:
        raise ValueError("syntax: job upload ID")
    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        if upload_args[0] == "retry":
            if len(upload_args) != 3:
                raise ValueError("syntax: job upload retry ID PLATFORM")
            _, job_id, retry_platform = upload_args
            manifest = service.get_job(job_id)
            selected_attempt = attempt_id
            if selected_attempt is None:
                attempt = next((item for item in reversed(manifest.upload_attempts)
                                if item["platform"] == retry_platform
                                and item["status"] == "failed"), None)
                if attempt is None:
                    raise ValueError("no failed upload attempt for that platform")
                selected_attempt = attempt["attempt_id"]
            result = service.retry_upload(
                job_id, retry_platform, selected_attempt, artifact_id,
                confirm_historical_artifact)
        else:
            if len(upload_args) != 1:
                raise ValueError("syntax: job upload ID")
            result = service.submit_upload(
                upload_args[0], platform, artifact_id,
                confirm_historical_artifact)
    _print_upload_result(result, json_output)


@job_app.command("uploads")
def job_uploads_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        status: Annotated[Optional[str], typer.Option(
            "--status", help="Keep only attempts in this status.")] = None,
        platform: Annotated[Optional[str], typer.Option(
            "--platform", help="Keep only attempts for this platform.")] = None,
        since: Annotated[Optional[str], typer.Option(
            "--since", help="Keep only attempts created at or after this "
            "ISO-8601 instant.")] = None,
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """List a job's upload attempt history with optional filters."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        attempts = service.list_upload_attempts(job_id, status, platform, since)
    if json_output:
        _print_json(attempts)
        return
    _print_table(f"Upload attempts for job {job_id}", [{
        "platform": attempt.get("platform"),
        "attempt_id": attempt.get("attempt_id"),
        "status": _status(attempt.get("status")),
        "scheduled_publish_at": attempt.get("scheduled_publish_at"),
    } for attempt in attempts],
        ["platform", "attempt_id", "status", "scheduled_publish_at"],
        nowrap=("attempt_id",))


@artifact_app.command("list")
def artifacts_list_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """List registered artifact revisions without their local paths."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        manifest = service.get_job(job_id)
        records = list(manifest.artifacts.values())
    if json_output:
        _print_json(records)
        return
    _print_table(f"Artifacts for job {job_id}", [{
        "artifact_id": item.get("id"),
        "revision": item.get("revision"),
        "kind": item.get("kind"),
        "display_name": item.get("display_name"),
        "state": _status(item.get("state")),
        "created_at": item.get("created_at"),
        "sha256": _short_hash(item.get("sha256")),
    } for item in records],
        ["artifact_id", "revision", "kind", "display_name", "state", "created_at",
         "sha256"], nowrap=("artifact_id",))


@artifact_app.command("preview")
def artifacts_preview_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        artifact_id: Annotated[str, typer.Argument(help="Registered artifact ID.")],
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Open a registered artifact in the default browser."""
    path = _artifact_path(ctx, job_id, artifact_id, data_dir, app_config)
    if not path.is_file():
        raise FileNotFoundError("artifact bytes are unavailable")
    webbrowser.open(path.resolve().as_uri())


@artifact_app.command("download")
def artifacts_download_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        artifact_id: Annotated[str, typer.Argument(help="Registered artifact ID.")],
        destination: Annotated[Path, typer.Option(
            "--destination", help="Local path the artifact is copied to.")],
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Copy a registered artifact to a local path."""
    path = _artifact_path(ctx, job_id, artifact_id, data_dir, app_config)
    shutil.copy2(path, destination)
    _print_summary([str(destination)])


@artifact_app.command("rename")
def artifacts_rename_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        artifact_id: Annotated[str, typer.Argument(help="Registered artifact ID.")],
        name: Annotated[str, typer.Option(
            "--name", help="New artifact display name.")],
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Change artifact display metadata without touching its bytes."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    if "/" in name or "\\" in name:
        raise ValueError("artifact display name must be a filename")
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        manifest = service.get_job(job_id)
        _registered_artifact(manifest, artifact_id)["display_name"] = name
        manifest.save(service.jobs_dir)


@artifact_app.command("delete")
def artifacts_delete_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        artifact_id: Annotated[str, typer.Argument(help="Registered artifact ID.")],
        yes: Annotated[bool, typer.Option(
            "--yes", help="Confirm the deletion.")] = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Trash local artifact bytes and keep a manifest tombstone."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        manifest = service.get_job(job_id)
        artifact = _registered_artifact(manifest, artifact_id)
        if not yes:
            raise ValueError("artifact delete requires --yes")
        service.storage.remove(artifact["storage"]["key"])
        artifact["state"] = "deleted"
        manifest.save(service.jobs_dir)


@artifact_app.command("prune")
def artifacts_prune_command(
        ctx: typer.Context,
        job_id: Annotated[str, typer.Argument(help="Job ID.")],
        json_output: JsonOption = False,
        data_dir: DataDirOption = None,
        app_config: AppConfigOption = None) -> None:
    """Apply the app.yml retention policy to superseded artifacts."""
    from clipmorph.service import JobService

    selected_data_dir, selected_config = _resolve_paths(ctx, data_dir, app_config)
    with closing(JobService(selected_data_dir,
                           app_config_path=selected_config)) as service:
        result = service.enforce_retention(job_id)
    if json_output:
        _print_json(result)
        return
    _print_fields(f"Retention for job {job_id}",
                  [("pruned", result.get("pruned")),
                   ("bytes_freed", result.get("bytes_freed"))])


app.add_typer(auth_app, name="auth")
app.add_typer(job_app, name="job")
app.add_typer(layout_app, name="layout")
job_app.add_typer(artifact_app, name="artifacts")

_command: Any = None


def _cli_command() -> Any:
    """Return the click command tree for the typer app, built once per process."""
    global _command
    if _command is None:
        _command = typer.main.get_command(app)
    return _command


def run_cli(argv: list[str] | None = None) -> int:
    """Execute one public command, returning the documented process status."""
    args = list(argv) if argv is not None else None
    _tolerate_unencodable_output()
    try:
        return _cli_command().main(args=args, prog_name=PROG_NAME,
                                   standalone_mode=False) or 0
    except _EXIT_ERRORS as error:
        return getattr(error, "exit_code", 0) or 0
    except _USAGE_ERROR as error:
        print(str(error) or "usage error", file=sys.stderr)
        return 2
    except _CLICK_EXCEPTION as error:
        print(str(error), file=sys.stderr)
        return 2
    except _ABORT_ERRORS:
        return 130
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
