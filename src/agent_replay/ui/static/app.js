document.addEventListener("DOMContentLoaded", () => {
  let allSessions = [];
  let currentSessionData = null;
  let currentFilter = "all";

  const sessionSearchInput = document.getElementById("session-search");
  const sessionsListEl = document.getElementById("sessions-list");
  const refreshBtn = document.getElementById("refresh-btn");
  const sessionCountBadge = document.getElementById("session-count-badge");

  const noSessionEl = document.getElementById("no-session-selected");
  const sessionDetailEl = document.getElementById("session-detail-view");

  const metricSessionId = document.getElementById("metric-session-id");
  const metricCost = document.getElementById("metric-cost");
  const metricDuration = document.getElementById("metric-duration");
  const metricEvents = document.getElementById("metric-events");
  const metricTokens = document.getElementById("metric-tokens");
  const flagsContainerEl = document.getElementById("flags-container");
  const timelineEventsEl = document.getElementById("timeline-events");

  const filterBtns = document.querySelectorAll(".filter-btn");

  async function fetchSessions() {
    try {
      sessionsListEl.innerHTML = `<div class="loading-state">Loading sessions...</div>`;
      const res = await fetch("/api/sessions");
      if (!res.ok) throw new Error("Failed to load sessions");
      allSessions = await res.json();
      sessionCountBadge.textContent = `${allSessions.length} Sessions`;
      renderSessionsList(allSessions);
    } catch (err) {
      sessionsListEl.innerHTML = `<div class="loading-state error">Error: ${err.message}</div>`;
    }
  }

  function renderSessionsList(sessions) {
    if (!sessions.length) {
      sessionsListEl.innerHTML = `<div class="loading-state">No recorded sessions yet.</div>`;
      return;
    }

    sessionsListEl.innerHTML = "";
    sessions.forEach(sess => {
      const item = document.createElement("div");
      item.className = `session-item ${currentSessionData && currentSessionData.session_id === sess.session_id ? 'active' : ''}`;
      
      const dateStr = sess.started_at ? new Date(sess.started_at).toLocaleTimeString() : "";
      const errorTag = sess.has_errors ? `<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #ef4444; font-size: 10px;">Error</span>` : "";

      item.innerHTML = `
        <div class="session-item-header">
          <span class="session-id">${sess.session_id}</span>
          ${errorTag}
        </div>
        <div class="session-item-footer">
          <span>${sess.event_count} events · ${dateStr}</span>
          <span class="cost-pill">$${Number(sess.total_cost_usd || 0).toFixed(6)}</span>
        </div>
      `;

      item.addEventListener("click", () => selectSession(sess.session_id));
      sessionsListEl.appendChild(item);
    });
  }

  async function selectSession(sessionId) {
    try {
      document.querySelectorAll(".session-item").forEach(el => el.classList.remove("active"));
      const res = await fetch(`/api/sessions/${sessionId}`);
      if (!res.ok) throw new Error("Failed to load session details");
      currentSessionData = await res.json();

      noSessionEl.classList.add("hidden");
      sessionDetailEl.classList.remove("hidden");

      renderSessionMetrics(currentSessionData);
      renderFlags(currentSessionData.flags || []);
      renderTimeline(currentSessionData.events || [], currentSessionData.flags || []);
      renderSessionsList(allSessions);
    } catch (err) {
      alert("Error loading session: " + err.message);
    }
  }

  function renderSessionMetrics(data) {
    metricSessionId.textContent = data.session_id;
    metricCost.textContent = `$${Number(data.total_cost_usd || 0).toFixed(6)}`;
    metricDuration.textContent = `${data.total_duration_ms} ms`;
    metricEvents.textContent = `${data.event_count} (${data.tool_calls_count} tools, ${data.model_calls_count} models)`;
    metricTokens.textContent = `${data.total_tokens_in.toLocaleString()} / ${data.total_tokens_out.toLocaleString()}`;
  }

  function renderFlags(flags) {
    if (!flagsContainerEl) return;
    flagsContainerEl.innerHTML = "";
    if (!flags.length) {
      flagsContainerEl.classList.add("hidden");
      return;
    }

    flagsContainerEl.classList.remove("hidden");
    flags.forEach(flag => {
      const banner = document.createElement("div");
      banner.className = `flag-banner ${flag.severity}`;
      const icon = flag.severity === "danger" ? "🚨" : "⚠️";
      banner.innerHTML = `
        <span>${icon}</span>
        <div>
          <strong>${flag.rule_name.replace(/_/g, " ").toUpperCase()}:</strong> ${flag.message}
        </div>
      `;
      flagsContainerEl.appendChild(banner);
    });
  }

  function renderTimeline(events, flags = []) {
    timelineEventsEl.innerHTML = "";
    const culpritSeqs = new Set();
    flags.forEach(f => (f.culprit_seqs || []).forEach(s => culpritSeqs.add(s)));

    const filtered = events.filter(e => {
      if (currentFilter === "all") return true;
      return e.type === currentFilter;
    });

    if (!filtered.length) {
      timelineEventsEl.innerHTML = `<div class="empty-state" style="height: 150px;">No events match filter.</div>`;
      return;
    }

    filtered.forEach(e => {
      const isCulprit = culpritSeqs.has(e.seq);
      const card = document.createElement("div");
      card.className = `timeline-card ${e.type} ${isCulprit ? 'culprit' : ''}`;

      let argsPretty = e.args_json;
      try {
        argsPretty = JSON.stringify(JSON.parse(e.args_json), null, 2);
      } catch (_) {}

      let resultPretty = e.result_json || "None";
      try {
        if (e.result_json) {
          resultPretty = JSON.stringify(JSON.parse(e.result_json), null, 2);
        }
      } catch (_) {}

      const tokenMeta = e.type === "model_call" 
        ? `<span>Tokens: ${e.tokens_in} in / ${e.tokens_out} out</span>` 
        : "";

      const errorBlock = e.error 
        ? `<div class="error-banner"><strong>Error:</strong> ${e.error}</div>` 
        : "";

      const culpritBadge = isCulprit ? `<span class="flag-pill">Flagged</span>` : "";

      card.innerHTML = `
        <div class="timeline-node-dot"></div>
        <div class="card-header">
          <div class="card-title-group">
            <span class="seq-badge">#${e.seq}</span>
            <span class="type-pill ${e.type}">${e.type === 'tool_call' ? 'Tool' : 'Model'}</span>
            <span class="event-name">${e.name}</span>
            ${culpritBadge}
          </div>
          <div class="card-meta-group">
            ${tokenMeta}
            <span>⏱️ ${e.duration_ms}ms</span>
            <span class="cost-pill">$${Number(e.cost_usd || 0).toFixed(6)}</span>
          </div>
        </div>

        ${errorBlock}

        <div class="accordion-section">
          <button class="accordion-toggle" onclick="this.nextElementSibling.classList.toggle('hidden')">
            ▶ Arguments & Inputs
          </button>
          <pre class="code-block hidden">${argsPretty}</pre>
        </div>

        <div class="accordion-section">
          <button class="accordion-toggle" onclick="this.nextElementSibling.classList.toggle('hidden')">
            ▶ Result & Outputs
          </button>
          <pre class="code-block hidden">${resultPretty}</pre>
        </div>
      `;

      timelineEventsEl.appendChild(card);
    });
  }

  // Event Listeners
  sessionSearchInput.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    const filtered = allSessions.filter(s => s.session_id.toLowerCase().includes(q));
    renderSessionsList(filtered);
  });

  refreshBtn.addEventListener("click", fetchSessions);

  filterBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      filterBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentFilter = btn.getAttribute("data-filter");
      if (currentSessionData) {
        renderTimeline(currentSessionData.events || [], currentSessionData.flags || []);
      }
    });
  });

  fetchSessions();
});