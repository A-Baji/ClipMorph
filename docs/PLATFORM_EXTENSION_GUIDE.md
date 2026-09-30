# Adding a platform

The mechanical checklist for adding a platform to ClipMorph. Each step names
the file, the symbol to extend, and the test that fails when the step is
skipped. Nothing here restates the configuration or credential contracts: read
[CONFIG_LAYERS.md](CONFIG_LAYERS.md) for the config schema, tiers, and merge
rules and [AUTHENTICATION.md](AUTHENTICATION.md) for credential fields and how
to obtain them, then work the steps in order.

Two ownership rules hold throughout. An adapter owns transport only: it sends
the fields `clipmorph/policy.py` composed and holds no content rule or
character limit of its own. `clipmorph/platforms.py` owns the supported set
and each platform's plain upload defaults, and every CLI, config, service, and
web surface reads them from there instead of keeping a second list.

The rules themselves, and their source links, are in
[PLATFORM_CAPABILITIES.md](PLATFORM_CAPABILITIES.md); the CLI and API contract
is in [CLI_WEB_PARITY.md](CLI_WEB_PARITY.md).

## Platform status

`- [x]` marks a platform that is registered in `SUPPORTED_PLATFORMS` and
covered by every test below. `- [ ]` marks one that is not registered yet.
`PlatformRegistryTests.test_guide_lists_exactly_supported_platforms` and
`PlatformCoverageDriftTests.test_extension_guide_marks_every_platform` fail
when these markers and the registry disagree, in either direction.

- [x] youtube
- [x] instagram
- [x] tiktok
- [x] twitter
- [ ] facebook ([#175](https://github.com/A-Baji/ClipMorph/issues/175))

## Steps

1. **Registry — `clipmorph/platforms.py`.** Add the platform id to
   `SUPPORTED_PLATFORMS` (`SUPPORTED_PLATFORMS_SET` derives from it), add
   `PLATFORM_TITLE` for the display name that surfaces render, add
   `PLATFORM_DEFAULT_CONFIG` in the same order as the tuple, using `{}` when
   the platform has no plain defaults, and add
   `SUPPORTED_NATIVE_SCHEDULING` in the same order. Config validation, the CLI,
   and the service all read the registry, so there is no second platform list to
   edit. A new `SUPPORTED_NATIVE_SCHEDULING` entry ships `False`: the platform
   may only be marked capable of holding a future publication after
   `quality/research/scheduling_probe.py` has passed against its live API, and
   that flip changes the registry and the capability doc together.
   *Fails without it:*
   `PlatformCoverageDriftTests.test_registry_declares_title_and_defaults_for_every_platform`,
   `PlatformRegistryTests.test_defaults_cover_every_supported_platform`, and
   `NativeSchedulingRegistryTests.test_registry_covers_every_supported_platform`.

2. **Capability rule — `clipmorph/policy.py`.** Add a `CapabilityRule` to
   `CAPABILITY_MATRIX`: the duration, size, and codec bounds the platform
   enforces, its `caption_limit`, the `content_mode` that maps `upload.content`
   onto the adapter's fields (`separate`, `combined`, or `caption`), and the
   positional `output_keys` the adapter's `run` method accepts. This rule, not
   the adapter, decides what text is sent and how long it may be.
   *Fails without it:*
   `PlatformCoverageDriftTests.test_policy_matrix_documents_every_platform` and
   `PlatformRegistryTests.test_every_supported_platform_has_a_policy_rule`.

3. **Transport adapter — `clipmorph/upload_pipeline/platforms/<name>.py`.**
   Add `class <Name>UploadPipeline(BaseUploadPipeline)` that uploads the
   prepared file and returns the platform's response. The title, description,
   keywords, caption, or tweet text arrive already composed and bounded by the
   capability rule. Export the class from
   `clipmorph/upload_pipeline/platforms/__init__.py`, add the
   `<platform>: bool = False` keyword to `UploadPipeline.__init__` in
   `clipmorph/upload_pipeline/__init__.py`, and wire its
   `self.enabled_platforms` branch to the class; submissions enable a platform
   by passing that keyword from `clipmorph/upload_attempts.py`. Lazy-import
   rules apply: heavy media and ML dependencies stay out of the `--help` and
   `init` paths.
   *Fails without it:*
   `PlatformCoverageDriftTests.test_adapter_module_and_pipeline_keyword_exist_for_every_platform`.

4. **Upload options and credentials surface — `clipmorph/platforms.py`,
   `clipmorph/auth.py`, and `clipmorph/preflight.py`.** Plain per-platform
   defaults live in `PLATFORM_DEFAULT_CONFIG`; explicit
   `upload.platforms.<platform>` config values become `<platform>_<option>` keys
   and win over the default in `UploadPipeline._map_common_parameters`. There is
   no per-platform options route and no per-platform CLI flag to generate, and
   none is needed: the CLI runtime summary and the `GET /api/v1/credentials`
   display both read the registry. Add the platform's environment-key schema to
   `AUTH_ENVIRONMENT_KEYS` so `auth status` and `auth set <platform>` list it,
   and its credential names to `PLATFORM_CREDENTIALS`, which preflight indexes
   by platform id. The credentials route (`PUT /api/v1/credentials/<platform>`)
   is platform-generic and needs no edit.
   *Fails without it:*
   `PlatformCoverageDriftTests.test_cli_defaults_mapping_covers_every_platform`,
   `PlatformCoverageDriftTests.test_web_credential_surface_covers_every_platform`,
   `PlatformCoverageDriftTests.test_preflight_credentials_cover_every_platform`,
   and `tests/test_auth.py::test_auth_schema_exposes_only_consumed_credentials`
   (a declared field no adapter reads is drift).

5. **Policy docs — `docs/PLATFORM_CAPABILITIES.md`.** Add a row to the static
   artifact rules table linking the platform's own API or product
   documentation, a row to the upload metadata rules table with its
   `content_mode`, `output_keys`, and `caption_limit`; that table mirrors
   `CAPABILITY_MATRIX`, and a row to the native publish scheduling table naming
   whether the platform can hold a future publication and which adapter
   parameter does it. A new or changed rule also moves `POLICY_VERSION` in
   `clipmorph/policy.py` and the document's "Last reviewed" line to the same
   publication date, because the runtime reports that date as the policy
   version.
   *Fails without it:*
   `PlatformCoverageDriftTests.test_capability_doc_documents_every_platform`,
   `tests/test_policy_metadata.py::DocumentedMetadataRuleTests`, and
   `NativeSchedulingRegistryTests.test_capability_doc_cell_matches_the_registry`.

6. **Parity — `docs/CLI_WEB_PARITY.md`.** Name the platform id in the CLI
   upload row so the contract covers it, pointing at `SUPPORTED_PLATFORMS` as
   the source of truth rather than duplicating the rules. API rows stay
   platform-generic: credentials, upload submission, and per-platform retry
   already take the platform as a path or body value.
   *Fails without it:*
   `PlatformCoverageDriftTests.test_parity_cli_rows_reference_every_platform`.

7. **Frontend — `frontend/src/App.svelte`.** Add the platform id to the
   `platforms` const. The nav's job-form platform list, the upload draft
   platform checkboxes, and the Settings credential status list all iterate that
   const, so do not add a second literal for an upload surface; build the
   dashboard (`frontend/dist`) through its own workflow when the change needs a
   rebuilt asset.
   *Fails without it:*
   `PlatformCoverageDriftTests.test_frontend_platforms_const_lists_every_platform`.

8. **Docs health and the drift suite.** Run the focused suite and the
   documentation check; the full gate list is in `AGENTS.md`.
   *Fails without it:* nothing — this is the step that reports the others.

   ```text
   python -m unittest discover -s tests -p "test_platforms.py" -v
   python -m unittest discover -s tests
   python scripts/check_docs.py
   ```
