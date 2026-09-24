<script>
  let activeView = 'Queue';
  let selectedJob = 'midnight-ranked';
  let showAdvanced = false;
  let theme = 'system';
  let notice = '';
  let liveJobs = false;
  let configuration = { data_dir: '%LOCALAPPDATA%/ClipMorph', generate_previews: true };
  let captionSegments = [
    { start: 0.0, end: 1.8, text: 'Wait for the timing.', speaker: 'speaker_1', censored: false, emphasis: false },
    { start: 1.8, end: 4.6, text: 'That was absolutely unreal.', speaker: 'speaker_2', censored: false, emphasis: true },
    { start: 4.6, end: 7.2, text: 'Push now, push now!', speaker: 'speaker_1', censored: false, emphasis: false }
  ];
  let activeSegment = 1;
  $: currentJob = jobs.find((job) => job.id === selectedJob) || jobs[0];

  async function loadLiveJobs() {
    try {
      const response = await fetch('/api/v1/jobs');
      if (!response.ok) return;
      const manifests = await response.json();
      if (!Array.isArray(manifests) || !manifests.length) return;
      jobs = manifests.map((manifest) => ({
        id: manifest.job_id,
        title: manifest.configuration?.title || manifest.source_path.split(/[\\/]/).pop(),
        source: manifest.source_path.split(/[\\/]/).pop(),
        duration: manifest.configuration?.duration || '--:--',
        state: manifest.status,
        progress: manifest.status === 'completed' || manifest.status === 'published' ? 100 : 0,
        tone: manifest.status === 'failed' ? 'amber' : manifest.status === 'completed' ? 'green' : 'blue',
        updated: manifest.updated_at
      }));
      selectedJob = jobs[0].id;
      liveJobs = true;
    } catch (error) {
      liveJobs = false;
    }
  }

  async function loadConfiguration() {
    try {
      const response = await fetch('/api/v1/configuration');
      if (response.ok) {
        const result = await response.json();
        configuration = { ...configuration, ...(result.configuration || {}) };
      }
    } catch (error) {
      // Keep the visual form usable when the frontend is previewed standalone.
    }
  }

  loadLiveJobs();
  loadConfiguration();

  const nav = [
    { label: 'Queue', icon: '◫', count: '04' },
    { label: 'Captions', icon: 'Aa' },
    { label: 'Layouts', icon: '▦' },
    { label: 'Uploads', icon: '↗' },
    { label: 'Settings', icon: '◎' }
  ];

  let jobs = [
    { id: 'midnight-ranked', title: 'Midnight ranked / clutch round', source: 'session_2026-09-23.mp4', duration: '18:42', state: 'Rendering', progress: 68, tone: 'amber', updated: '2 min ago' },
    { id: 'tower-push', title: 'Tower push / no comms', source: 'stream_0918.mov', duration: '07:16', state: 'Waiting review', progress: 100, tone: 'blue', updated: '14 min ago' },
    { id: 'clean-ace', title: 'Clean ace / final zone', source: 'ranked-night.mp4', duration: '04:03', state: 'Uploaded', progress: 100, tone: 'green', updated: 'Yesterday' },
    { id: 'warmup', title: 'Warmup highlights', source: 'warmup.mkv', duration: '22:31', state: 'Queued', progress: 0, tone: 'muted', updated: 'Yesterday' }
  ];

  function selectJob(job) {
    selectedJob = job.id;
    activeView = 'Queue';
  }

  function saveSettings() {
    fetch('/api/v1/configuration', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ configuration })
    }).then(() => {
      notice = 'Configuration saved locally';
      setTimeout(() => notice = '', 2600);
    }).catch(() => {
      notice = 'Configuration preview updated';
      setTimeout(() => notice = '', 2600);
    });
  }

  async function saveCaptions() {
    if (liveJobs) {
      try {
        const jobResponse = await fetch(`/api/v1/jobs/${selectedJob}`);
        const job = await jobResponse.json();
        const session = {
          schema_version: 1,
          source_sha256: job.source_sha256,
          media_duration: null,
          original_segments: captionSegments,
          segments: captionSegments
        };
        await fetch(`/api/v1/jobs/${selectedJob}/transcript`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(session)
        });
      } catch (error) {
        notice = 'Caption edits kept in this review session';
      }
    }
    notice = 'Caption edits saved to the job';
    setTimeout(() => notice = '', 2600);
  }
</script>

<svelte:head>
  <title>ClipMorph / Studio</title>
</svelte:head>

<div class="shell">
  <aside class="rail">
    <div class="brand-mark" aria-label="ClipMorph home"><span>CM</span><i></i></div>
    <div class="rail-label">Workspace</div>
    <nav aria-label="Primary navigation">
      {#each nav as item}
        <button class:active={activeView === item.label} class="nav-item" onclick={() => activeView = item.label}>
          <span class="nav-icon">{item.icon}</span>
          <span>{item.label}</span>
          {#if item.count}<em>{item.count}</em>{/if}
        </button>
      {/each}
    </nav>
    <div class="rail-bottom">
      <div class="health-dot"><span></span> Local service <b>online</b></div>
      <button class="avatar" aria-label="Open profile">AB</button>
    </div>
  </aside>

  <main class="content">
    <header class="topbar">
      <div>
        <p class="eyebrow">Wednesday, 23 September 2026 <span>•</span> local workspace</p>
        <h1>{activeView === 'Queue' ? 'Your edit queue' : activeView}</h1>
      </div>
      <div class="top-actions">
        <button class="icon-button" aria-label="Toggle theme" title="Theme" onclick={() => theme = theme === 'system' ? 'dark' : 'system'}>◐</button>
        <button class="service-pill" onclick={() => activeView = 'Settings'}><span></span> {liveJobs ? 'Service connected' : 'Preview data'} <b>⌄</b></button>
      </div>
    </header>

    {#if notice}<div class="toast" role="status">✓ {notice}</div>{/if}

    {#if activeView === 'Queue'}
      <section class="command-row">
        <div class="stat-block"><strong>04</strong><span>active jobs</span></div>
        <div class="stat-block"><strong>02</strong><span>need your review</span></div>
        <div class="stat-block"><strong>07</strong><span>published this week</span></div>
        <button class="primary-action" onclick={() => notice = 'Choose a video to start a new job'}><span>＋</span> New job</button>
      </section>

      <section class="queue-layout">
        <div class="job-list">
          <div class="section-heading"><div><span class="section-kicker">Pipeline</span><h2>Recent jobs</h2></div><button class="text-button">Filter <span>⌄</span></button></div>
          {#each jobs as job}
            <button class:selected={selectedJob === job.id} class="job-row" onclick={() => selectJob(job)}>
              <div class="thumb thumb-{job.tone}"><span>{job.state === 'Rendering' ? '68%' : job.state === 'Uploaded' ? '✓' : '▶'}</span></div>
              <div class="job-copy"><div class="job-title">{job.title}</div><div class="job-meta">{job.source} <span>·</span> {job.duration}</div></div>
              <div class="job-state"><span class="state-dot {job.tone}"></span>{job.state}<small>{job.updated}</small></div>
              <span class="row-arrow">→</span>
            </button>
          {/each}
          <button class="load-more">View all jobs <span>→</span></button>
        </div>

        <div class="detail-panel">
          <div class="detail-head"><div><span class="section-kicker">Selected job</span><h2>{currentJob.title}</h2></div><button class="more-button" aria-label="More job actions">•••</button></div>
          <div class="preview-frame"><div class="preview-scan"></div><div class="preview-title">{currentJob.title}</div><div class="preview-badge">{currentJob.duration}</div><div class="play-button">▶</div><div class="preview-caption">You can’t teach this timing.</div></div>
          <div class="progress-line"><div style={`width: ${currentJob.progress}%`}></div></div>
          <div class="detail-status"><div><strong>{currentJob.state}</strong><span>{currentJob.progress}% complete</span></div><span class="mono">{currentJob.state === 'Rendering' ? '00:11:42 / 00:18:42' : 'ready'}</span></div>
          <div class="platforms"><div class="platform-head"><span>Destinations</span><span>Upload status</span></div><div class="platform-row"><span class="platform-icon youtube">Y</span><b>YouTube Shorts</b><span class="upload-ok">{currentJob.state === 'Uploaded' ? 'Published' : 'Ready'}</span></div><div class="platform-row"><span class="platform-icon instagram">◎</span><b>Instagram Reels</b><span class="upload-pending">{currentJob.state === 'Uploaded' ? 'Published' : 'Waiting'}</span></div><div class="platform-row"><span class="platform-icon tiktok">♪</span><b>TikTok</b><span class="upload-pending">{currentJob.state === 'Uploaded' ? 'Published' : 'Waiting'}</span></div></div>
          <div class="detail-actions"><button class="secondary-action" onclick={() => notice = 'Opening caption review'}>Review captions</button><button class="quiet-action" aria-label="Download artifact">↓</button><button class="quiet-action" aria-label="More actions">•••</button></div>
        </div>
      </section>
    {:else if activeView === 'Captions'}
      <section class="caption-page"><div class="section-heading"><div><span class="section-kicker">Review before render</span><h2>Caption studio</h2></div><button class="primary-action" onclick={saveCaptions}>Save caption edits</button></div><div class="caption-layout"><div class="caption-preview"><div class="caption-video"><span class="preview-badge">00:02.80</span><div class="caption-frame-text">That was absolutely unreal.</div><div class="timeline-play">▶</div></div><div class="timeline"><div class="timeline-track"><span class="timeline-progress"></span><i style="left: 34%"></i></div><div class="timeline-labels"><span>00:00</span><span>00:09.42</span></div></div></div><div class="segment-panel"><div class="segment-panel-head"><div><span class="section-kicker">Transcript</span><h3>{captionSegments.length} segments</h3></div><button class="text-button">Original ↔ Edited</button></div>{#each captionSegments as segment, index}<button class:active-segment={activeSegment === index} class="segment-row" onclick={() => activeSegment = index}><span class="segment-time">{segment.start.toFixed(1)}<br /><b>{segment.end.toFixed(1)}</b></span><span class="segment-text">{segment.text}</span><span class="speaker-swatch {segment.speaker === 'speaker_2' ? 'lime' : ''}"></span></button>{/each}<button class="add-segment" onclick={() => captionSegments = [...captionSegments, { start: 7.2, end: 8.5, text: 'New caption', speaker: 'speaker_1', censored: false, emphasis: false }]}>＋ Add segment</button></div></div><div class="caption-controls"><div class="control-heading"><span class="section-kicker">Selected segment</span><span class="mono">{captionSegments[activeSegment].start.toFixed(1)}s — {captionSegments[activeSegment].end.toFixed(1)}s</span></div><label class="edit-field">Caption text<textarea bind:value={captionSegments[activeSegment].text} rows="2"></textarea></label><div class="timing-fields"><label class="edit-field">Start<input type="number" step="0.1" bind:value={captionSegments[activeSegment].start} /></label><label class="edit-field">End<input type="number" step="0.1" bind:value={captionSegments[activeSegment].end} /></label></div><div class="timing-fields"><label class="edit-field">Speaker<input bind:value={captionSegments[activeSegment].speaker} /></label><label class="edit-field">Replacement<input placeholder="Optional" /></label></div><div class="toggle-row"><label><input type="checkbox" bind:checked={captionSegments[activeSegment].censored} /> Censor word</label><label><input type="checkbox" bind:checked={captionSegments[activeSegment].emphasis} /> Emphasis</label></div></div></section>
    {:else if activeView === 'Settings'}
      <section class="settings-page"><div class="section-heading"><div><span class="section-kicker">Workspace</span><h2>Configuration</h2></div><button class="primary-action" onclick={saveSettings}>Save changes</button></div><div class="settings-grid"><div class="setting-card"><span class="card-index">01</span><h3>Default destinations</h3><p>Choose where finished clips go when a job completes.</p><label><input type="checkbox" checked /> YouTube Shorts</label><label><input type="checkbox" checked /> Instagram Reels</label><label><input type="checkbox" /> TikTok</label></div><div class="setting-card"><span class="card-index">02</span><h3>Local storage</h3><p>Jobs and artifacts stay on this machine.</p><label class="field-label">Data directory<input bind:value={configuration.data_dir} /></label><label><input type="checkbox" checked={configuration.generate_previews} onchange={(event) => configuration.generate_previews = event.currentTarget.checked} /> Generate previews automatically</label></div><div class="setting-card advanced"><button class="advanced-toggle" onclick={() => showAdvanced = !showAdvanced}><span>Advanced controls</span><span>{showAdvanced ? '−' : '+'}</span></button>{#if showAdvanced}<label class="field-label">Transcription model<select><option>large-v3</option><option>medium</option><option>small</option></select></label><label class="field-label">Worker limit<input type="number" value="2" /></label>{/if}</div></div></section>
    {:else}
      <section class="empty-view"><div class="empty-icon">{nav.find((item) => item.label === activeView)?.icon}</div><h2>{activeView} is ready for the next slice</h2><p>The local service foundation is connected. This view will share the same job and artifact model as the queue.</p><button class="primary-action" onclick={() => activeView = 'Queue'}>Back to queue</button></section>
    {/if}
  </main>
</div>
