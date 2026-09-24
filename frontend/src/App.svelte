<script>
  let activeView = 'Queue';
  let selectedJob = 'midnight-ranked';
  let showAdvanced = false;
  let theme = 'system';
  let notice = '';
  $: currentJob = jobs.find((job) => job.id === selectedJob) || jobs[0];

  const nav = [
    { label: 'Queue', icon: '◫', count: '04' },
    { label: 'Captions', icon: 'Aa' },
    { label: 'Layouts', icon: '▦' },
    { label: 'Uploads', icon: '↗' },
    { label: 'Settings', icon: '◎' }
  ];

  const jobs = [
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
    notice = 'Configuration saved locally';
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
        <button class="service-pill" onclick={() => activeView = 'Settings'}><span></span> Service ready <b>⌄</b></button>
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
    {:else if activeView === 'Settings'}
      <section class="settings-page"><div class="section-heading"><div><span class="section-kicker">Workspace</span><h2>Configuration</h2></div><button class="primary-action" onclick={saveSettings}>Save changes</button></div><div class="settings-grid"><div class="setting-card"><span class="card-index">01</span><h3>Default destinations</h3><p>Choose where finished clips go when a job completes.</p><label><input type="checkbox" checked /> YouTube Shorts</label><label><input type="checkbox" checked /> Instagram Reels</label><label><input type="checkbox" /> TikTok</label></div><div class="setting-card"><span class="card-index">02</span><h3>Local storage</h3><p>Jobs and artifacts stay on this machine.</p><label class="field-label">Data directory<input value="%LOCALAPPDATA%/ClipMorph" /></label><label><input type="checkbox" checked /> Generate previews automatically</label></div><div class="setting-card advanced"><button class="advanced-toggle" onclick={() => showAdvanced = !showAdvanced}><span>Advanced controls</span><span>{showAdvanced ? '−' : '+'}</span></button>{#if showAdvanced}<label class="field-label">Transcription model<select><option>large-v3</option><option>medium</option><option>small</option></select></label><label class="field-label">Worker limit<input type="number" value="2" /></label>{/if}</div></div></section>
    {:else}
      <section class="empty-view"><div class="empty-icon">{nav.find((item) => item.label === activeView)?.icon}</div><h2>{activeView} is ready for the next slice</h2><p>The local service foundation is connected. This view will share the same job and artifact model as the queue.</p><button class="primary-action" onclick={() => activeView = 'Queue'}>Back to queue</button></section>
    {/if}
  </main>
</div>
