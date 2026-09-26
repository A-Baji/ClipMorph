<script>
  const platforms = ['youtube', 'instagram', 'tiktok', 'twitter'];
  const nav = ['Queue', 'New Job', 'Captions', 'Layouts', 'Uploads', 'Settings'];
  let activeView = 'Queue';
  let jobs = [];
  let sources = [];
  let layouts = [];
  let artifacts = [];
  let uploadAttempts = [];
  let selectedJobId = '';
  let selectedSources = [];
  let expandedSource = '';
  let perSourceOverrides = {};
  let credentials = {};
  let configuration = { source_dir: 'sources', output_dir: 'output', job_defaults: {}, layouts: [] };
  let transcript = null;
  let notice = '';
  let errors = [];
  let sourceFile;
  let busy = false;
  let compositionJson = '{}';
  let jobForm = {
    title: '', description: '', tags: '', no_confirm: false, clean: false,
    conversion_skip: false, subtitles_skip: false, strict: false,
    renderer: 'overlay', layout_id: '', upload_skip: false,
    include: [...platforms], exclude: [], dry_run: false,
  };
  let layoutForm = {
    name: 'Vertical highlight', crop: false, crop_x: 0, crop_y: 0,
    crop_width: 320, crop_height: 240, sizing: 'fit', composition: 'overlay',
    placement: 'top', renderer: 'overlay', caption: true, caption_text: '',
  };
  let uploadDraft = { title: '', description: '', tags: '' };
  let uploadPlatforms = [...platforms];

  $: selectedJob = jobs.find((job) => job.job_id === selectedJobId) || jobs[0];
  $: selectedCheckpoint = selectedJob?.checkpoints?.[selectedJob?.current_checkpoint];

  function flash(message) {
    notice = message;
    setTimeout(() => notice = '', 3200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = body.error;
      throw new Error(error?.message || body.detail?.message || body.detail || `Request failed (${response.status})`);
    }
    return body;
  }

  const jsonOptions = (method, body) => ({
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  async function loadWorkspace() {
    try {
      [jobs, sources, layouts] = await Promise.all([
        api('/api/v1/jobs'), api('/api/v1/sources'), api('/api/v1/layouts'),
      ]);
      const settings = await api('/api/v1/configuration');
      configuration = settings.configuration || configuration;
      credentials = settings.credentials || {};
      if (!selectedJobId && jobs.length) selectedJobId = jobs[0].job_id;
      if (selectedJobId && jobs.some((job) => job.job_id === selectedJobId)) {
        await loadJobDetails();
      }
    } catch (error) {
      errors = [error.message];
      flash('Local service is unavailable');
    }
  }

  async function loadJobDetails() {
    if (!selectedJobId) return;
    const [job, artifactList, attempts] = await Promise.all([
      api(`/api/v1/jobs/${selectedJobId}`),
      api(`/api/v1/jobs/${selectedJobId}/artifacts`),
      api(`/api/v1/jobs/${selectedJobId}/uploads`),
    ]);
    jobs = jobs.map((item) => item.job_id === selectedJobId ? job : item);
    artifacts = artifactList;
    uploadAttempts = attempts;
    uploadDraft = {
      title: job.configuration?.upload?.content?.title || '',
      description: job.configuration?.upload?.content?.description || '',
      tags: (job.configuration?.upload?.content?.tags || []).join(', '),
    };
    compositionJson = JSON.stringify(job.configuration?.conversion?.layout || {}, null, 2);
  }

  async function setView(view) {
    errors = [];
    if (view === 'New Job') await loadSources();
    if (view === 'Uploads' && selectedJob) await loadJobDetails();
    if (view === 'Captions' && selectedJob) await loadTranscript();
    activeView = view;
  }

  async function loadSources() {
    try { sources = await api('/api/v1/sources'); }
    catch (error) { errors = [error.message]; }
  }

  function handleFile(event) { sourceFile = event.currentTarget.files[0]; }

  function setSelectedSource(name, checked) {
    selectedSources = checked
      ? [...new Set([...selectedSources, name])]
      : selectedSources.filter((source) => source !== name);
  }

  function setPerSourceOverride(source, key, value) {
    const next = { ...(perSourceOverrides[source] || {}) };
    if (value === '') delete next[key];
    else next[key] = value;
    perSourceOverrides = { ...perSourceOverrides, [source]: next };
  }

  function sharedOverrides() {
    return {
      general: { no_confirm: jobForm.no_confirm, clean: jobForm.clean },
      conversion: {
        skip: jobForm.conversion_skip,
        strict: jobForm.strict,
        subtitles: { skip: jobForm.subtitles_skip, renderer: jobForm.renderer },
        ...(jobForm.layout_id ? { layout_id: jobForm.layout_id } : {}),
      },
      upload: {
        skip: jobForm.upload_skip,
        content: {
          title: jobForm.title,
          description: jobForm.description,
          tags: jobForm.tags ? jobForm.tags.split(',').map((tag) => tag.trim()).filter(Boolean) : [],
        },
        platforms: { include: jobForm.include, exclude: jobForm.exclude },
      },
    };
  }

  async function submitJobs() {
    busy = true;
    errors = [];
    try {
      if (sourceFile) {
        const form = new FormData();
        form.append('file', sourceFile);
        const uploaded = await api('/api/v1/sources', { method: 'POST', body: form });
        selectedSources = [...new Set([...selectedSources, uploaded.name])];
        sourceFile = null;
      }
      const sourceNames = selectedSources.length ? selectedSources : null;
      const configuredSources = sourceNames || sources.map((source) => source.name);
      const jobConfigs = configuredSources.map((source) => {
        const contentOverrides = perSourceOverrides[source] || {};
        const content = {};
        for (const key of ['title', 'description', 'tags']) {
          const value = contentOverrides[key];
          if (typeof value === 'string' && value.trim()) {
            content[key] = key === 'tags'
              ? value.split(',').map((tag) => tag.trim()).filter(Boolean)
              : value;
          }
        }
        return {
          general: { source },
          ...(Object.keys(content).length ? { upload: { content } } : {}),
        };
      });
      const payload = { source_names: sourceNames, job_configs: jobConfigs, overrides: sharedOverrides() };
      if (jobForm.dry_run) {
        const validation = await api('/api/v1/jobs/validate', jsonOptions('POST', payload));
        if (!validation.valid) {
          errors = validation.failed.map((item) => `${item.source || 'record'}: ${item.message}`);
          return;
        }
        flash(`Validation passed for ${validation.summary.created} source(s)`);
        return;
      }
      const result = await api('/api/v1/jobs/bulk', jsonOptions('POST', payload));
      await loadWorkspace();
      if (result.created.length) selectedJobId = result.created[0].job_id;
      await loadJobDetails();
      activeView = 'Queue';
      flash(`${result.summary.created} created · ${result.summary.skipped} skipped · ${result.summary.failed} failed`);
      if (result.failed.length) errors = result.failed.map((item) => `${item.source || 'record'}: ${item.message}`);
    } catch (error) {
      errors = [error.message];
    } finally {
      busy = false;
    }
  }

  async function selectJob(jobId) {
    selectedJobId = jobId;
    try {
      await loadJobDetails();
      if (activeView === 'Captions') await loadTranscript();
    } catch (error) { errors = [error.message]; }
  }

  async function jobAction(action) {
    if (!selectedJob) return;
    try {
      if (action === 'delete') {
        if (!window.confirm('Move this job and its local output to trash?')) return;
        await api(`/api/v1/jobs/${selectedJob.job_id}?confirm=true`, { method: 'DELETE' });
        selectedJobId = '';
      } else {
        await api(`/api/v1/jobs/${selectedJob.job_id}/${action}`,
          jsonOptions('POST', action === 'cancel' ? { confirm: true } : {}));
      }
      await loadWorkspace();
      flash(action === 'cancel' ? 'Cancellation requested' : `${action} accepted`);
    } catch (error) { errors = [error.message]; }
  }

  async function acceptCheckpoint(stage) {
    if (!selectedJob) return;
    const checkpoint = selectedJob.checkpoints[stage];
    try {
      await api(`/api/v1/jobs/${selectedJob.job_id}/checkpoints/${stage}/accept`,
        jsonOptions('POST', { expected_revision: checkpoint.revision }));
      await loadWorkspace();
      flash(`${stage} review accepted`);
    } catch (error) { errors = [error.message]; }
  }

  async function loadTranscript() {
    if (!selectedJob?.active_transcript) { transcript = null; return; }
    try {
      transcript = await api(`/api/v1/jobs/${selectedJob.job_id}/transcript`);
      transcript.segments = transcript.segments.map((segment) => ({
        ...segment, typography: { ...(segment.typography || {}) },
      }));
    }
    catch (error) { errors = [error.message]; }
  }

  function updateSegmentTypography(segment, key, value) {
    const typography = { ...(segment.typography || {}) };
    if (key === 'bold' || key === 'italic' || key === 'underline') {
      typography[key] = value;
    } else if (value === '') {
      delete typography[key];
    } else {
      typography[key] = key === 'size' ? Number(value) : value;
    }
    segment.typography = typography;
    transcript = { ...transcript, segments: [...transcript.segments] };
  }

  function updateSegmentTime(segment, key, value) {
    segment[key] = Number(value);
    transcript = { ...transcript, segments: [...transcript.segments] };
  }

  async function saveTranscript() {
    if (!selectedJob || !transcript || !selectedJob.active_transcript) return;
    try {
      const checkpoint = selectedJob.checkpoints.transcript;
      transcript = await api(`/api/v1/jobs/${selectedJob.job_id}/transcript`,
        jsonOptions('PUT', {
          ...transcript,
          expected_revision: selectedJob.active_transcript.revision,
          expected_checkpoint_revision: checkpoint.revision,
        }));
      await loadWorkspace();
      flash('Transcript revision saved');
    } catch (error) { errors = [error.message]; }
  }

  async function saveComposition() {
    if (!selectedJob) return;
    let layout;
    try { layout = JSON.parse(compositionJson); }
    catch (error) { errors = [`Invalid layout JSON: ${error.message}`]; return; }
    const reopen = selectedJob.status === 'completed'
      ? window.confirm('Reopen this completed job to change its composition?')
      : false;
    if (selectedJob.status === 'completed' && !reopen) return;
    try {
      await api(`/api/v1/jobs/${selectedJob.job_id}/configuration`, jsonOptions('PATCH', {
        patch: { conversion: { layout } },
        expected_configuration_hash: selectedJob.current_configuration_hash,
        reopen,
      }));
      await loadWorkspace();
      await loadJobDetails();
      flash('Job composition saved; render the updated composition');
    } catch (error) { errors = [error.message]; }
  }

  async function saveUploadDraft() {
    if (!selectedJob) return;
    try {
      const checkpoint = selectedJob.checkpoints.upload;
      const upload = structuredClone(selectedJob.configuration.upload || {});
      upload.content = {
        ...(upload.content || {}),
        title: uploadDraft.title,
        description: uploadDraft.description,
        tags: uploadDraft.tags
          .split(',').map((tag) => tag.trim()).filter(Boolean),
      };
      upload.platforms = { ...(upload.platforms || {}), include: uploadPlatforms };
      await api(`/api/v1/jobs/${selectedJob.job_id}/checkpoints/upload`,
        jsonOptions('PUT', { expected_revision: checkpoint.revision, upload }));
      await loadWorkspace();
      flash('Upload draft saved for review');
    } catch (error) { errors = [error.message]; }
  }

  async function submitUpload() {
    if (!selectedJob) return;
    try {
      await saveUploadDraft();
      await loadWorkspace();
      await api(`/api/v1/jobs/${selectedJob.job_id}/upload`,
        jsonOptions('POST', { platforms: uploadPlatforms }));
      await loadWorkspace();
      flash('Upload attempts started');
    } catch (error) { errors = [error.message]; }
  }

  async function retryUpload(attempt) {
    try {
      await api(`/api/v1/jobs/${selectedJob.job_id}/uploads/${attempt.platform}/retry`,
        jsonOptions('POST', { attempt_id: attempt.attempt_id }));
      await loadJobDetails();
      flash(`${attempt.platform} retry started`);
    } catch (error) { errors = [error.message]; }
  }

  async function saveLayout() {
    const layout = {};
    if (layoutForm.crop) {
      layout.crop = {
        enabled: true,
        source: { x: Number(layoutForm.crop_x), y: Number(layoutForm.crop_y),
          width: Number(layoutForm.crop_width), height: Number(layoutForm.crop_height) },
        sizing: { mode: layoutForm.sizing, ...(layoutForm.sizing === 'native' ? {} : {
          dimensions: { width: 640, height: 360 },
        }) },
        composition: { mode: layoutForm.composition, placement: layoutForm.placement },
      };
    }
    layout.captions = layoutForm.renderer === 'overlay'
      ? { overlay: { items: layoutForm.caption ? [{
          text: layoutForm.caption_text || 'ClipMorph', placement: 'center',
        }] : [] } }
      : { stacked: { placement: layoutForm.placement, panel: { color: 'black' },
          padding: { left: 32, top: 20 }, items: layoutForm.caption ? [{
            text: layoutForm.caption_text || 'ClipMorph',
          }] : [] } };
    try {
      await api('/api/v1/layouts', jsonOptions('POST', { name: layoutForm.name, layout }));
      layouts = await api('/api/v1/layouts');
      flash('Layout saved');
    } catch (error) { errors = [error.message]; }
  }

  async function deleteLayout(id) {
    if (!window.confirm('Delete this global layout preset?')) return;
    try {
      await api(`/api/v1/layouts/${id}?confirm=true`, { method: 'DELETE' });
      layouts = await api('/api/v1/layouts');
      flash('Layout removed');
    } catch (error) { errors = [error.message]; }
  }

  async function renameArtifact(artifact) {
    const displayName = window.prompt('New artifact display name', artifact.display_name);
    if (!displayName || !selectedJob) return;
    try {
      await api(`/api/v1/jobs/${selectedJob.job_id}/artifacts/${artifact.id}`,
        jsonOptions('PATCH', { display_name: displayName }));
      await loadJobDetails();
    } catch (error) { errors = [error.message]; }
  }

  async function deleteArtifact(artifact) {
    if (!selectedJob || !window.confirm('Move these local artifact bytes to trash?')) return;
    try {
      await api(`/api/v1/jobs/${selectedJob.job_id}/artifacts/${artifact.id}?confirm=true`,
        { method: 'DELETE' });
      await loadJobDetails();
      flash('Artifact moved to trash');
    } catch (error) { errors = [error.message]; }
  }

  async function saveSettings() {
    try {
      await api('/api/v1/configuration', jsonOptions('PUT', { configuration }));
      flash('app.yml saved');
    } catch (error) { errors = [error.message]; }
  }

  loadWorkspace();
</script>

<svelte:head>
  <title>ClipMorph / Studio</title>
  <link rel="icon" href="data:," />
</svelte:head>

<div class="shell">
  <aside class="rail">
    <div class="brand-mark"><span>CM</span><i></i></div>
    <div class="rail-label">Workspace</div>
    <nav aria-label="Primary navigation">
      {#each nav as item}
        <button class:active={activeView === item} class="nav-item" onclick={() => setView(item)}>
          <span class="nav-icon">{item === 'New Job' ? '+' : item[0]}</span>
          <span>{item}</span>
          {#if item === 'Queue'}<em>{jobs.length.toString().padStart(2, '0')}</em>{/if}
        </button>
      {/each}
    </nav>
    <div class="rail-bottom">
      <div class="health-dot"><span></span> Local service <b>connected</b></div>
      <div class="avatar">CM</div>
    </div>
  </aside>

  <main class="content">
    <header class="topbar">
      <div><p class="eyebrow">ClipMorph <span>•</span> local workspace</p><h1>{activeView === 'Queue' ? 'Your edit queue' : activeView}</h1></div>
      <button class="service-pill" onclick={() => setView('Settings')}><span></span> app.yml <b>⌄</b></button>
    </header>
    {#if notice}<div class="toast" role="status">{notice}</div>{/if}
    {#if errors.length}<div class="error-box" role="alert">{#each errors as error}<div>{error}</div>{/each}</div>{/if}

    {#if activeView === 'Queue'}
      <section class="command-row">
        <div class="stat-block"><strong>{jobs.length.toString().padStart(2, '0')}</strong><span>jobs</span></div>
        <div class="stat-block"><strong>{jobs.filter((job) => job.current_checkpoint).length.toString().padStart(2, '0')}</strong><span>checkpoints open</span></div>
        <div class="stat-block"><strong>{jobs.filter((job) => job.status === 'completed').length.toString().padStart(2, '0')}</strong><span>complete</span></div>
        <button class="primary-action" onclick={() => setView('New Job')}>＋ New job</button>
      </section>
      <section class="queue-layout">
        <div class="job-list">
          <div class="section-heading"><div><span class="section-kicker">Pipeline</span><h2>Recent jobs</h2></div><button class="text-button" onclick={loadWorkspace}>Refresh ↻</button></div>
          {#if !jobs.length}<div class="empty-inline">No jobs yet. Select a source to begin.</div>{/if}
          {#each jobs as job}
            <button class:selected={selectedJobId === job.job_id} class="job-row" onclick={() => selectJob(job.job_id)}>
              <div class="thumb"><span>{job.status === 'completed' ? '✓' : '▶'}</span></div>
              <div class="job-copy"><div class="job-title">{job.configuration?.upload?.content?.title || job.configuration?.general?.source}</div><div class="job-meta">{job.configuration?.general?.source} <span>·</span> {job.status}</div></div>
              <div class="job-state"><span class="state-dot"></span>{job.current_checkpoint || job.status}<small>{job.updated_at}</small></div><span class="row-arrow">→</span>
            </button>
          {/each}
        </div>
        {#if selectedJob}
          <div class="detail-panel">
            <div class="detail-head"><div><span class="section-kicker">Selected job</span><h2>{selectedJob.configuration?.upload?.content?.title || selectedJob.job_id}</h2></div><span class="mono">{selectedJob.status}</span></div>
            <div class="preview-frame"><div class="preview-scan"></div><div class="preview-title">{selectedJob.configuration?.general?.source}</div><div class="play-button">▶</div><div class="preview-caption">{selectedJob.current_checkpoint || 'No review pending'}</div></div>
            <div class="platforms"><div class="platform-head"><span>CHECKPOINTS</span><span>STATE</span></div>
              {#each ['transcript', 'conversion', 'upload'] as stage}
                <div class="platform-row"><span class="platform-icon">{stage[0].toUpperCase()}</span><span>{stage}</span><span class="upload-pending">{selectedJob.checkpoints?.[stage]?.status}</span></div>
              {/each}
            </div>
            <div class="detail-actions">
              {#if selectedJob.current_checkpoint}<button class="primary-action" onclick={() => setView(selectedJob.current_checkpoint === 'upload' ? 'Uploads' : 'Captions')}>Review {selectedJob.current_checkpoint}</button>{/if}
              {#if ['failed', 'cancelled', 'partial_failure'].includes(selectedJob.status)}<button class="secondary-action" onclick={() => jobAction('resume')}>Resume job</button>{/if}
              <button class="quiet-action" onclick={() => jobAction('cancel')} aria-label="Cancel job">×</button>
              <button class="quiet-action" onclick={() => jobAction('delete')} aria-label="Delete job">⌫</button>
            </div>
          </div>
        {/if}
      </section>

    {:else if activeView === 'New Job'}
      <section class="form-page">
        <div class="section-heading"><div><span class="section-kicker">Independent jobs · shared overrides</span><h2>Select sources</h2></div><button class="primary-action" disabled={busy} onclick={submitJobs}>{jobForm.dry_run ? 'Validate' : 'Create jobs'}</button></div>
        <div class="form-grid">
          <div class="form-card wide">
            <label class="field-label">Upload a source<input type="file" accept="video/*" onchange={handleFile} /></label>
            <div class="field-row"><button class="text-button" onclick={() => selectedSources = sources.map((source) => source.name)}>Select all</button><button class="text-button" onclick={() => selectedSources = []}>Clear selection</button><span class="mono">{selectedSources.length} selected</span></div>
            {#each sources as source}
              <div class="source-entry">
                <label class="source-option"><input type="checkbox" checked={selectedSources.includes(source.name)} onchange={(event) => setSelectedSource(source.name, event.currentTarget.checked)} /><span>{source.name}</span><small>{source.size} bytes</small></label>
                <button class="text-button" aria-expanded={expandedSource === source.name} onclick={() => expandedSource = expandedSource === source.name ? '' : source.name}>Overrides: {source.name}</button>
                {#if expandedSource === source.name}
                  <div class="source-override">
                    <span class="card-index">PER-CLIP OVERRIDES</span>
                    <label class="field-label">Clip title<input aria-label="Clip title" value={perSourceOverrides[source.name]?.title || ''} oninput={(event) => setPerSourceOverride(source.name, 'title', event.currentTarget.value)} /></label>
                    <label class="field-label">Clip description<textarea value={perSourceOverrides[source.name]?.description || ''} oninput={(event) => setPerSourceOverride(source.name, 'description', event.currentTarget.value)} rows="2"></textarea></label>
                    <label class="field-label">Clip tags<input value={perSourceOverrides[source.name]?.tags || ''} oninput={(event) => setPerSourceOverride(source.name, 'tags', event.currentTarget.value)} placeholder="tag one, tag two" /></label>
                  </div>
                {/if}
              </div>
            {/each}
            <label class="field-label">Title override<input bind:value={jobForm.title} placeholder="Leave empty to use each filename" /></label>
            <label class="field-label">Description<textarea bind:value={jobForm.description} rows="3"></textarea></label>
            <label class="field-label">Tags<input bind:value={jobForm.tags} placeholder="clutch, ranked, highlights" /></label>
          </div>
          <div class="form-card">
            <span class="card-index">PIPELINE</span>
            {#each [['dry_run','Validate only'], ['conversion_skip','Skip conversion'], ['subtitles_skip','Skip transcript'], ['upload_skip','Skip upload'], ['strict','Strict validation'], ['no_confirm','Auto-accept reviews'], ['clean','Clean generated files']] as option}
              <label><input type="checkbox" bind:checked={jobForm[option[0]]} /> {option[1]}</label>
            {/each}
            <span class="card-index">DESTINATIONS</span>
            {#each platforms as platform}
              <label><input type="checkbox" checked={jobForm.include.includes(platform)} onchange={(event) => jobForm.include = event.currentTarget.checked ? [...jobForm.include, platform] : jobForm.include.filter((item) => item !== platform)} /> {platform}</label>
            {/each}
          </div>
          <div class="form-card wide">
            <span class="card-index">CONVERSION</span>
            <div class="field-row"><label class="field-label">Layout preset<select bind:value={jobForm.layout_id}><option value="">No preset</option>{#each layouts as layout}<option value={layout.id}>{layout.name}</option>{/each}</select></label><label class="field-label">Generated caption renderer<select bind:value={jobForm.renderer}><option value="overlay">Overlay</option><option value="stacked">Stacked</option></select></label></div>
          </div>
        </div>
      </section>

    {:else if activeView === 'Captions'}
      <section class="form-page">
        <div class="section-heading"><div><span class="section-kicker">Source-bound review</span><h2>Transcript and composition</h2></div><div class="top-actions"><button class="secondary-action" onclick={saveTranscript} disabled={!transcript}>Save transcript revision</button><button class="primary-action" onclick={() => acceptCheckpoint('transcript')} disabled={selectedJob?.checkpoints?.transcript?.status !== 'awaiting_review'}>Accept transcript</button></div></div>
        {#if !selectedJob}<div class="empty-inline">Select a job from the queue.</div>
        {:else if transcript}
          <div class="caption-layout"><div class="segment-panel"><div class="segment-panel-head"><div><span class="section-kicker">Revision {transcript.revision}</span><h3>{transcript.segments.length} segments</h3></div></div>
            {#each transcript.segments as segment, index}
              <div class="segment-review">
                <div class="segment-row">
                  <label class="field-label">Start<input aria-label={`Segment ${index + 1} start time`} type="number" min="0" step="0.01" value={segment.start} oninput={(event) => updateSegmentTime(segment, 'start', event.currentTarget.value)} /></label>
                  <label class="field-label">End<input aria-label={`Segment ${index + 1} end time`} type="number" min="0" step="0.01" value={segment.end} oninput={(event) => updateSegmentTime(segment, 'end', event.currentTarget.value)} /></label>
                  <textarea aria-label={`Transcript segment ${index + 1}`} bind:value={segment.text}></textarea>
                </div>
                <details class="segment-typography"><summary>Text styling</summary>
                  <div class="field-row">
                    <label class="field-label">Size<input aria-label={`Segment ${index + 1} font size`} type="number" min="1" value={segment.typography.size || ''} oninput={(event) => updateSegmentTypography(segment, 'size', event.currentTarget.value)} /></label>
                    <label class="field-label">Color<input aria-label={`Segment ${index + 1} color`} value={segment.typography.color || ''} placeholder="Automatic" oninput={(event) => updateSegmentTypography(segment, 'color', event.currentTarget.value)} /></label>
                  </div>
                  <div class="field-row">
                    {#each ['bold', 'italic', 'underline'] as style}
                      <label><input aria-label={`Segment ${index + 1} ${style}`} type="checkbox" checked={Boolean(segment.typography[style])} onchange={(event) => updateSegmentTypography(segment, style, event.currentTarget.checked)} /> {style}</label>
                    {/each}
                  </div>
                </details>
              </div>
            {/each}
          </div><div class="caption-controls"><span class="card-index">COMPOSITION REVIEW</span><label class="field-label">Job layout JSON<textarea aria-label="Job composition layout" rows="16" spellcheck="false" bind:value={compositionJson}></textarea></label><button class="secondary-action" onclick={saveComposition}>Save job composition</button><button class="secondary-action" onclick={() => jobAction('render')}>Render current composition</button><button class="primary-action" onclick={() => acceptCheckpoint('conversion')} disabled={selectedJob.checkpoints?.conversion?.status !== 'awaiting_review'}>Accept composition</button></div></div>
        {:else}<div class="empty-view"><h2>No transcript review pending</h2><p>This job has no active transcript revision to edit.</p></div>{/if}
      </section>

    {:else if activeView === 'Layouts'}
      <section class="form-page"><div class="section-heading"><div><span class="section-kicker">Global registry</span><h2>Layouts</h2></div><button class="primary-action" onclick={saveLayout}>Save layout</button></div>
        <div class="layout-grid"><div class="form-card"><label class="field-label">Preset name<input bind:value={layoutForm.name} /></label><label><input type="checkbox" bind:checked={layoutForm.crop} /> Enable source crop</label>
          {#if layoutForm.crop}<div class="field-row">{#each [['crop_x','X'],['crop_y','Y'],['crop_width','Width'],['crop_height','Height']] as field}<label class="field-label">{field[1]}<input type="number" min="0" bind:value={layoutForm[field[0]]} /></label>{/each}</div><label class="field-label">Sizing<select bind:value={layoutForm.sizing}><option value="fit">Fit</option><option value="stretch">Stretch</option><option value="native">Native</option></select></label><label class="field-label">Composition<select bind:value={layoutForm.composition}><option value="overlay">Overlay</option><option value="stacked">Stacked</option></select></label>{/if}
          <label class="field-label">Placement<select bind:value={layoutForm.placement}><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></select></label><label class="field-label">Caption collection<select bind:value={layoutForm.renderer}><option value="overlay">Overlay</option><option value="stacked">Stacked</option></select></label><label><input type="checkbox" bind:checked={layoutForm.caption} /> Add caption item</label><label class="field-label">Caption text<input bind:value={layoutForm.caption_text} /></label>
        </div><div class="saved-list"><span class="section-kicker">Saved presets</span>{#each layouts as layout}<div class="saved-row"><div><b>{layout.name}</b><small>{layout.id}</small></div><button class="quiet-action" onclick={() => deleteLayout(layout.id)} aria-label="Delete layout">×</button></div>{/each}</div></div>
      </section>

    {:else if activeView === 'Uploads'}
      <section class="form-page"><div class="section-heading"><div><span class="section-kicker">Pre-upload checkpoint</span><h2>Content and artifact</h2></div><div class="top-actions"><button class="secondary-action" onclick={saveUploadDraft}>Save draft</button><button class="primary-action" onclick={submitUpload}>Submit upload</button></div></div>
        {#if !selectedJob}<div class="empty-view"><h2>Select a job first</h2></div>{:else}<div class="upload-layout"><div class="form-card upload-draft-fields"><span class="card-index">UPLOAD DRAFT</span><label class="field-label">Title<input aria-label="Upload title" bind:value={uploadDraft.title} /></label><label class="field-label">Description<textarea aria-label="Upload description" rows="4" bind:value={uploadDraft.description}></textarea></label><label class="field-label">Tags<input aria-label="Upload tags" bind:value={uploadDraft.tags} placeholder="tag one, tag two" /></label>
          {#each platforms as platform}<label><input type="checkbox" checked={uploadPlatforms.includes(platform)} onchange={(event) => uploadPlatforms = event.currentTarget.checked ? [...uploadPlatforms, platform] : uploadPlatforms.filter((item) => item !== platform)} /> {platform}</label>{/each}
          <span class="card-index">ARTIFACTS</span>{#each artifacts as artifact}<div class="saved-row"><div><b>{artifact.display_name || artifact.kind} · r{artifact.revision}</b><small>{artifact.state} · {artifact.sha256 || 'unavailable'}</small></div><a class="text-button" href={`/api/v1/jobs/${selectedJob.job_id}/artifacts/${artifact.id}/preview`} target="_blank">Preview</a><a class="text-button" href={`/api/v1/jobs/${selectedJob.job_id}/artifacts/${artifact.id}/download`}>Download</a><button class="quiet-action" onclick={() => renameArtifact(artifact)} aria-label="Rename artifact">✎</button><button class="quiet-action" onclick={() => deleteArtifact(artifact)} aria-label="Delete artifact">×</button></div>{/each}
        </div><div class="form-card"><span class="card-index">ATTEMPT HISTORY</span>{#each uploadAttempts as attempt}<div class="saved-row"><div><b>{attempt.platform} · {attempt.status}</b><small>{attempt.configuration_snapshot?.content?.title} · {attempt.artifact_hash}</small></div>{#if attempt.status === 'failed'}<button class="text-button" onclick={() => retryUpload(attempt)}>Retry</button>{/if}</div>{/each}</div></div>{/if}
      </section>

    {:else if activeView === 'Settings'}
      <section class="form-page"><div class="section-heading"><div><span class="section-kicker">Persistent app configuration</span><h2>Workspace settings</h2></div><button class="primary-action" onclick={saveSettings}>Save app.yml</button></div><div class="settings-grid"><div class="form-card"><span class="card-index">PATHS</span><label class="field-label">Source directory<input bind:value={configuration.source_dir} /></label><label class="field-label">Output directory<input bind:value={configuration.output_dir} /></label></div><div class="form-card"><span class="card-index">CREDENTIAL STATUS</span>{#each platforms as platform}<div class="health-row"><span class:healthy={credentials[platform]}></span><b>{platform}</b><small>{credentials[platform] ? 'configured' : 'not configured'}</small></div>{/each}</div><div class="form-card wide"><span class="card-index">GLOBAL JOB DEFAULTS</span><label class="field-label">Default title<input bind:value={configuration.job_defaults.upload.content.title} /></label><label class="field-label">Default description<textarea bind:value={configuration.job_defaults.upload.content.description} rows="3"></textarea></label></div></div></section>
    {/if}
  </main>
</div>