<script>
  import Card from '../components/Card.svelte';
  import Field from '../components/Field.svelte';
  import HealthRow from '../components/HealthRow.svelte';
  import { app, saveSettings, probeCredential } from '../lib/store.svelte.js';

  /** Workspace configuration. Paths and credentials first; defaults advanced. */
  let settings = $state({
    source_dir: '',
    output_dir: '',
    defaultTitle: '',
    defaultDescription: '',
  });

  $effect(() => {
    const configuration = app.configuration;
    settings.source_dir = configuration.source_dir ?? '';
    settings.output_dir = configuration.output_dir ?? '';
    settings.defaultTitle = configuration.job_defaults?.upload?.content?.title ?? '';
    settings.defaultDescription = configuration.job_defaults?.upload?.content?.description ?? '';
  });

  function save() {
    const configuration = $state.snapshot(app.configuration);
    configuration.source_dir = settings.source_dir;
    configuration.output_dir = settings.output_dir;
    configuration.job_defaults = configuration.job_defaults || {};
    configuration.job_defaults.upload = configuration.job_defaults.upload || {};
    configuration.job_defaults.upload.content = configuration.job_defaults.upload.content || {};
    configuration.job_defaults.upload.content.title = settings.defaultTitle;
    configuration.job_defaults.upload.content.description = settings.defaultDescription;
    app.configuration = configuration;
    saveSettings();
  }
</script>

<div class="content">
  <div class="section-head">
    <div>
      <h2>Settings</h2>
      <p>Workspace paths, credentials, and the defaults every new job starts from.</p>
    </div>
    <button class="btn btn-primary" onclick={save}>Save app.yml</button>
  </div>

  <div class="grid-2">
    <Card title="Paths">
      <div class="stack">
        <Field label="Source directory" hint="Where ClipMorph looks for clips to convert.">
          <input bind:value={settings.source_dir} />
        </Field>
        <Field label="Output directory" hint="Where finished vertical clips are written.">
          <input bind:value={settings.output_dir} />
        </Field>
      </div>
    </Card>

    <Card title="Credentials" description="Probing is opt-in and read-only.">
      <div class="stack-tight">
        {#each app.platforms as platform (platform)}
          <HealthRow
            {platform}
            configured={Boolean(app.credentials[platform])}
            probe={app.probeResults[platform]}
            onProbe={probeCredential}
          />
        {/each}
      </div>
    </Card>
  </div>

  <Card title="Global job defaults" description="Applied to every new job before per-job overrides.">
    <details class="advanced">
      <summary>Default upload content</summary>
      <div class="advanced-body">
        <Field label="Default title">
          <input bind:value={settings.defaultTitle} />
        </Field>
        <Field label="Default description">
          <textarea bind:value={settings.defaultDescription} rows="3"></textarea>
        </Field>
      </div>
    </details>
  </Card>
</div>
