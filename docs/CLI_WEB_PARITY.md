# CLI to Web Parity Matrix

This checked-in matrix is the release gate for the local dashboard. Every CLI
control has a visual control, API field, validation boundary, runtime
destination, and focused test. The CLI and API both create the same
`JobManifest` and use the same workflow runner.

| CLI item | Visual control | API field/route | Validation | Runtime destination | Test |
| --- | --- | --- | --- | --- | --- |
| `--help` | service startup help | `clipmorph --help` | argparse | `cli.py` | `test_cli.py` |
| `--init`, `--config-path` | Settings template action | `PUT /configuration` | config schema | `create_config_template` | `test_cli.py` |
| input path / picker | New Job source controls | `POST /sources`, `POST /jobs` | source exists/uploaded | `JobManifest.source_path` | `test_web.py` |
| `--data-dir` | Settings data directory | service constructor | writable path | `JobService` | `test_cli.py` |
| `--dry-run` | New Job run mode | `POST /jobs/validate` | effective config/errors | validation response | `test_web.py` |
| `--resume JOB_ID` | Queue Resume action | `POST /jobs/{id}/resume` | failed/cancelled state | `JobService.resume_job` | `test_web.py` |
| batch processing | multi-source submission | `POST /batches` | source list | shared `batch_id` | `test_web.py` |
| cancellation | Queue Cancel action | `POST /jobs/{id}/cancel` | explicit confirmation | `CancellationToken` | `test_web.py` |
| `--clean` | artifact cleanup confirmation | `DELETE /jobs/{id}` | explicit confirmation | `send2trash` | `test_web.py` |
| `--no-confirm` | submit without prompt | job configuration | boolean | workflow | `test_cli.py` |
| `--no-conversion` | Run mode checkbox | configuration field | boolean | `execute_job` | `test_web.py` |
| `--strict` | strict validation checkbox | configuration field | boolean | conversion pipeline | `test_cli.py` |
| `--layout` | Layout preset selector | `GET/POST /layouts` | `validate_layout` | configuration layout | `test_web.py` |
| `--no-cam`, `--cam-*` | conversion geometry controls | configuration fields | preflight geometry | conversion pipeline | `test_cli.py` |
| `--output-dir` | output directory | configuration field | output validation | conversion pipeline | `test_cli.py` |
| `--no-subs` | skip captions checkbox | configuration field | boolean | conversion pipeline | `test_cli.py` |
| `--reviewed-transcript` | Captions review entry | transcript GET/PUT | source hash/schema | transcript artifact | `test_web.py` |
| transcription language/model/device/compute | transcription controls | configuration fields | choices/defaults | transcription pipeline | `test_cli.py` |
| caption text/timing/speaker/censor/emphasis | Captions editor | transcript GET/PUT | transcript schema | transcript artifact | `test_web.py` |
| `--no-upload` | upload toggle | configuration field | boolean | workflow | `test_cli.py` |
| `--upload-to`, `--skip` | destination checkboxes | configuration fields | platform choices | `execute_job` | `test_cli.py` |
| title/description/tags | New Job content fields | configuration fields | title/preflight | upload pipeline | `test_web.py` |
| platform overrides | Settings policy section | configuration fields | platform schema | upload pipeline | `test_cli.py` |
| credentials | Settings health rows | `GET/PUT /configuration` | masked secret handling | platform clients | `test_web.py` |
| upload and retry | Uploads actions | `/upload`, `/uploads/{platform}/retry` | artifact/platform state | upload pipeline | `test_web.py` |
| artifact preview/download/rename/delete | Uploads artifact actions | artifacts routes | confirmation/trash | job manifest/artifact | `test_web.py` |

## Differential contract

`POST /api/v1/jobs/validate` accepts the same normalized configuration keys
that the CLI parser places in a `JobManifest`. Differential tests compare the
effective configuration, warnings, and lifecycle destination before either
path performs conversion or upload. No live platform credentials are needed.