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
  const metricOutcomes = document.getElementById("metric-outcomes");
  const metricSlowest = document.getElementById("metric-slowest");
  const eventSearchInput = document.getElementById("event-search");
  const eventStatusFilter = document.getElementById("event-status-filter");
  const toolStatsEl = document.getElementById("tool-stats");
  const flagsContainerEl = document.getElementById("flags-container");
  const timelineEventsEl = document.getElementById("timeline-events");
  const replaySessionSelect = document.getElementById("replay-session-select");
  const replayModeSelect = document.getElementById("replay-mode-select");
  const runReplayBtn = document.getElementById("run-replay-btn");
  const replayResultsEl = document.getElementById("replay-results");
  const runExperimentBtn = document.getElementById("run-experiment-btn");
  const experimentResultsEl = document.getElementById("experiment-results");
  const pricingExchangeNote = document.getElementById("pricing-exchange-note");
  const pricingTableBody = document.getElementById("pricing-table-body");
  const savePricingBtn = document.getElementById("save-pricing-btn");
  const costHistoryEl = document.getElementById("cost-history");
  const detectorConfigForm = document.getElementById("detector-config-form");
  const saveDetectorBtn = document.getElementById("save-detector-btn");
  const detectorConfigStatus = document.getElementById("detector-config-status");
  const liveScenarioSelect = document.getElementById("live-scenario-select");
  const runLiveBtn = document.getElementById("run-live-btn");
  const liveRunStatusEl = document.getElementById("live-run-status");

  const filterBtns = document.querySelectorAll(".filter-btn");
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");
  const sidebarLinks = document.querySelectorAll(".sidebar-link");
  const sidebar = document.getElementById("app-sidebar");
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const sidebarOverlay = document.getElementById("sidebar-overlay");
  const overviewMetrics = document.getElementById("overview-metrics");
  const overviewRecent = document.getElementById("overview-recent");
  const playgroundForm = document.getElementById("playground-form");
  const playgroundProvider = document.getElementById("playground-provider");
  const playgroundModel = document.getElementById("playground-model");
  const playgroundPrompt = document.getElementById("playground-prompt");
  const playgroundMessages = document.getElementById("playground-messages");
  const providerNotice = document.getElementById("provider-notice");
  const playgroundSend = document.getElementById("playground-send");
  const usageProviderFilter = document.getElementById("usage-provider-filter");
  const usageModelFilter = document.getElementById("usage-model-filter");
  const usageSessionFilter = document.getElementById("usage-session-filter");
  const usageTableBody = document.getElementById("usage-table-body");

  function switchTab(tabName) {
    tabBtns.forEach(btn => {
      const isActive = btn.dataset.tab === tabName;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-selected", String(isActive));
    });

    tabPanels.forEach(panel => {
      const isActive = panel.dataset.panel === tabName;
      panel.classList.toggle("active", isActive);
      panel.hidden = !isActive;
    });
    sidebarLinks.forEach(link => link.classList.toggle("active", link.dataset.tab === tabName));
    window.localStorage.setItem("agent-replay-section", tabName);
    if (window.matchMedia("(max-width: 850px)").matches) {
      sidebar.classList.remove("mobile-open");
      sidebarOverlay.hidden = true;
    }
    if (tabName === "overview") fetchOverview();
    if (tabName === "playground") fetchProviders();
    if (tabName === "cost") {
      fetchPricing();
      fetchCostHistory();
      fetchUsage();
    }

    async function fetchUsage() {
      const summary = document.getElementById("usage-summary");
      try {
        const params = new URLSearchParams();
        if (usageProviderFilter.value) params.set("provider", usageProviderFilter.value);
        if (usageModelFilter.value) params.set("model", usageModelFilter.value);
        if (usageSessionFilter.value) params.set("session_id", usageSessionFilter.value);
        const data = await (await fetch(`/api/usage?${params}`)).json();
        summary.replaceChildren();
        if (!data.groups.length) {
          summary.textContent = "No recorded model usage is available yet. Configure a provider and submit a playground request.";
          usageTableBody.replaceChildren();
          return;
        }
        usageTableBody.replaceChildren();
        data.groups.forEach(group => {
          const tableRow = document.createElement("tr");
          const cost = group.cost_status === "unavailable"
            ? "Unavailable"
            : `$${group.cost_usd.toFixed(8)} (${group.cost_status})`;
          [
            `${group.provider} / ${group.model}`,
            group.sessions,
            group.input_tokens,
            group.output_tokens,
            cost,
          ].forEach(value => {
            const cell = document.createElement("td");
            cell.textContent = String(value);
            tableRow.appendChild(cell);
          });
          usageTableBody.appendChild(tableRow);
          const row = document.createElement("div");
          row.className = "usage-row";
          row.textContent = `${group.provider} / ${group.model} · ${group.input_tokens} in · ${group.output_tokens} out · ${cost}`;
          summary.appendChild(row);
        });
        if (!usageProviderFilter.dataset.loaded) {
          const providers = [...new Set(data.groups.map(group => group.provider))].sort();
          const models = [...new Set(data.groups.map(group => group.model))].sort();
          const sessions = data.sessions.map(session => session.session_id).sort();
          for (const [select, values] of [[usageProviderFilter, providers], [usageModelFilter, models], [usageSessionFilter, sessions]]) {
            values.forEach(value => {
              const option = document.createElement("option");
              option.value = value;
              option.textContent = value;
              select.appendChild(option);
            });
          }
          usageProviderFilter.dataset.loaded = "true";
        }
      } catch (err) {
        summary.textContent = `Unable to load model usage: ${err.message}`;
      }
    }

    async function fetchOverview() {
      try {
        const data = await (await fetch("/api/overview")).json();
        overviewMetrics.replaceChildren();
        [
          ["Recorded sessions", data.session_count],
          ["Recorded events", data.event_count],
          ["Successful events", data.successful_events],
          ["Failed events", data.failed_events],
          ["Event duration", `${data.total_duration_ms} ms`],
          ["Model usage", data.model_usage_available ? "Available" : "Unavailable"],
        ].forEach(([label, value]) => {
          const card = document.createElement("div");
          card.className = "metric-card";
          card.innerHTML = `<span class="metric-label">${label}</span><span class="metric-value">${value}</span>`;
          overviewMetrics.appendChild(card);
        });
        overviewRecent.replaceChildren();
        data.recent_sessions.forEach(session => {
          const item = document.createElement("button");
          item.className = "overview-session";
          item.type = "button";
          item.textContent = `${session.session_id} · ${session.event_count} events`;
          item.addEventListener("click", () => selectSession(session.session_id).then(() => switchTab("timeline")));
          overviewRecent.appendChild(item);
        });
      } catch (err) {
        overviewRecent.textContent = `Unable to load overview: ${err.message}`;
      }
    }

    async function fetchProviders() {
      try {
        const data = await (await fetch("/api/providers")).json();
        playgroundProvider.replaceChildren();
        data.providers.forEach(provider => {
          const option = document.createElement("option");
          option.value = provider.id;
          option.textContent = `${provider.label}${provider.configured ? "" : " (not configured)"}`;
          option.disabled = !provider.configured;
          playgroundProvider.appendChild(option);
        });
        const available = data.providers.filter(provider => provider.configured);
        providerNotice.textContent = available.length
          ? `${available.length} provider(s) configured. Calls are made only after you press Send.`
          : "No provider API keys are configured. Offline recording, replay, and experiments remain available.";
      } catch (err) {
        providerNotice.textContent = `Unable to load provider configuration: ${err.message}`;
      }
    }

    playgroundForm.addEventListener("submit", async event => {
      event.preventDefault();
      playgroundSend.disabled = true;
      const userMessage = document.createElement("div");
      userMessage.className = "chat-message user";
      userMessage.textContent = playgroundPrompt.value;
      playgroundMessages.appendChild(userMessage);
      try {
        const response = await fetch("/api/playground/chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            provider: playgroundProvider.value,
            model: playgroundModel.value || null,
            prompt: playgroundPrompt.value,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Provider request failed.");
        const assistant = document.createElement("div");
        assistant.className = "chat-message assistant";
        assistant.textContent = `${data.text}\n\nUsage: ${data.usage ? JSON.stringify(data.usage) : "Unavailable"} · Cost: ${data.cost_usd ?? "Unavailable"}`;
        playgroundMessages.appendChild(assistant);
        playgroundPrompt.value = "";
      } catch (err) {
        providerNotice.textContent = err.message;
      } finally {
        playgroundSend.disabled = false;
      }
    });
    document.getElementById("playground-reset").addEventListener("click", () => playgroundMessages.replaceChildren());
    sidebarToggle.addEventListener("click", () => {
      if (window.matchMedia("(max-width: 850px)").matches) {
        sidebar.classList.toggle("mobile-open");
        sidebarOverlay.hidden = !sidebar.classList.contains("mobile-open");
      } else {
        sidebar.classList.toggle("collapsed");
      }
    });
    sidebarOverlay.addEventListener("click", () => {
      sidebar.classList.remove("mobile-open");
      sidebarOverlay.hidden = true;
    });
    sidebarLinks.forEach(link => link.addEventListener("click", () => switchTab(link.dataset.tab === "sessions" ? "timeline" : link.dataset.tab)));
    if (tabName === "detector") fetchDetectorConfig();
    if (tabName === "live") fetchLiveScenarios();
  }

  const detectorFields = [
    ["max_repeated_tool_calls", "Repeat-call count", "1"],
    ["cost_multiplier_over_median", "Cost-spike multiplier", "0.1"],
    ["max_duration_ms", "Maximum session duration (ms)", "1"],
    ["max_events_per_session", "Maximum session events", "1"],
    ["min_sessions_for_cost_median", "Historical sessions for baseline", "1"],
  ];

  function renderDetectorConfig(config) {
    detectorConfigForm.replaceChildren();
    detectorFields.forEach(([field, labelText, step]) => {
      const label = document.createElement("label");
      label.className = "control-group";
      const caption = document.createElement("span");
      caption.className = "metric-label";
      caption.textContent = labelText;
      const input = document.createElement("input");
      input.type = "number";
      input.min = step === "0.1" ? "0.1" : "1";
      input.step = step;
      input.value = config[field];
      input.dataset.field = field;
      label.append(caption, input);
      detectorConfigForm.appendChild(label);
    });
  }

  async function fetchDetectorConfig() {
    try {
      const res = await fetch("/api/detector-config");
      if (!res.ok) throw new Error("Failed to load detector rules");
      renderDetectorConfig(await res.json());
    } catch (err) {
      detectorConfigStatus.textContent = err.message;
    }
  }

  async function saveDetectorConfig() {
    const config = {};
    detectorConfigForm.querySelectorAll("input").forEach(input => {
      config[input.dataset.field] = Number(input.value);
    });
    try {
      saveDetectorBtn.disabled = true;
      const res = await fetch("/api/detector-config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to save detector rules");
      renderDetectorConfig(data);
      detectorConfigStatus.textContent = "Detector rules saved.";
    } catch (err) {
      detectorConfigStatus.textContent = err.message;
    } finally {
      saveDetectorBtn.disabled = false;
    }
  }

  function renderPricing(data) {
    pricingExchangeNote.textContent = `Conversion rate: 1 USD = ${data.usd_to_inr} INR. Rates are saved to prices.json.`;
    pricingTableBody.replaceChildren();
    Object.entries(data.models).forEach(([model, rates]) => {
      const row = document.createElement("tr");
      row.dataset.model = model;
      const nameCell = document.createElement("td");
      nameCell.textContent = model;
      row.appendChild(nameCell);
      ["input_inr_per_1k", "output_inr_per_1k"].forEach(field => {
        const cell = document.createElement("td");
        const input = document.createElement("input");
        input.type = "number";
        input.min = "0";
        input.step = "0.000001";
        input.value = rates[field];
        input.dataset.field = field;
        cell.appendChild(input);
        row.appendChild(cell);
      });
      pricingTableBody.appendChild(row);
    });
  }

  async function fetchPricing() {
    try {
      const res = await fetch("/api/prices");
      if (!res.ok) throw new Error("Failed to load pricing");
      renderPricing(await res.json());
    } catch (err) {
      pricingExchangeNote.textContent = err.message;
    }
  }

  async function savePricing() {
    const models = {};
    pricingTableBody.querySelectorAll("tr").forEach(row => {
      const rates = {};
      row.querySelectorAll("input").forEach(input => {
        rates[input.dataset.field] = Number(input.value);
      });
      models[row.dataset.model] = rates;
    });
    try {
      savePricingBtn.disabled = true;
      const res = await fetch("/api/prices", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ models }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to save pricing");
      renderPricing(data);
    } catch (err) {
      pricingExchangeNote.textContent = err.message;
    } finally {
      savePricingBtn.disabled = false;
    }
  }

  function renderCostHistory(data) {
    costHistoryEl.replaceChildren();
    if (!data.points.length) {
      costHistoryEl.textContent = "No recorded session costs yet.";
      return;
    }
    const maxCost = Math.max(...data.points.map(point => Number(point.total_cost_usd)), 0);
    data.points.forEach(point => {
      const row = document.createElement("div");
      row.className = "cost-history-row";
      const label = document.createElement("span");
      label.className = "cost-history-label";
      label.textContent = point.session_id;
      const track = document.createElement("div");
      track.className = "cost-history-track";
      const bar = document.createElement("div");
      bar.className = "cost-history-bar";
      bar.style.width = `${maxCost ? (point.total_cost_usd / maxCost) * 100 : 2}%`;
      track.appendChild(bar);
      const value = document.createElement("span");
      value.textContent = `$${Number(point.total_cost_usd).toFixed(6)}`;
      row.append(label, track, value);
      costHistoryEl.appendChild(row);
    });
  }

  async function fetchCostHistory() {
    try {
      const res = await fetch("/api/cost-over-time");
      if (!res.ok) throw new Error("Failed to load cost history");
      renderCostHistory(await res.json());
    } catch (err) {
      costHistoryEl.textContent = err.message;
    }
  }

  function populateReplaySessions(sessions) {
    replaySessionSelect.replaceChildren();
    sessions.forEach(session => {
      const option = document.createElement("option");
      option.value = session.session_id;
      option.textContent = session.session_id;
      replaySessionSelect.appendChild(option);
    });
    if (currentSessionData) {
      replaySessionSelect.value = currentSessionData.session_id;
    }
  }

  function displayValue(value) {
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  }

  function renderReplayResults(data) {
    replayResultsEl.replaceChildren();
    data.events.forEach(event => {
      const row = document.createElement("div");
      row.className = `replay-row ${event.status}`;

      const summary = document.createElement("div");
      summary.className = "replay-row-summary";
      const label = document.createElement("span");
      label.className = "replay-event-label";
      label.textContent = `#${event.id} ${event.type === "tool_call" ? "Tool" : "Model"} ${event.name}`;
      const status = document.createElement("span");
      status.className = "replay-status";
      status.textContent = event.status;
      summary.append(label, status);
      row.appendChild(summary);

      if (event.status === "diverged") {
        const divergence = document.createElement("div");
        divergence.className = "replay-divergence";
        divergence.textContent = `Divergence at event #${event.id}: recorded ${displayValue(event.recorded)}; requested ${displayValue(event.requested)}. Replay halted, no response fabricated.`;
        row.appendChild(divergence);
      }

      if (event.type === "tool_call" && replayModeSelect.value === "forked") {
        const substitute = document.createElement("button");
        substitute.className = "btn btn-secondary replay-substitute-btn";
        substitute.type = "button";
        substitute.textContent = "Substitute";
        substitute.addEventListener("click", () => {
          const edited = window.prompt(
            "Edit the stored response JSON:",
            JSON.stringify(event.recorded_result ?? null)
          );
          if (edited === null) return;
          try {
            runReplay({ substituteSeq: event.id, substituteResult: JSON.parse(edited) });
          } catch (_) {
            replayResultsEl.textContent = "Substitution must be valid JSON.";
          }
        });
        row.appendChild(substitute);
      }
      replayResultsEl.appendChild(row);
    });
    if (!data.events.length) {
      replayResultsEl.textContent = "No replay events returned.";
    }
  }

  async function runReplay(options = {}) {
    const body = {
      session_id: replaySessionSelect.value,
      mode: replayModeSelect.value,
      ...options,
    };
    try {
      runReplayBtn.disabled = true;
      replayResultsEl.textContent = "Running replay...";
      const res = await fetch("/api/replay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Replay failed");
      renderReplayResults(data);
    } catch (err) {
      replayResultsEl.textContent = `Replay failed: ${err.message}`;
    } finally {
      runReplayBtn.disabled = false;
    }

  }

  function renderExperiment(data) {
    experimentResultsEl.replaceChildren();
    const summary = document.createElement("pre");
    summary.className = "code-block";
    summary.textContent = [
      `Experiment: ${data.experiment_id}`,
      `Parent session: ${data.parent_session_id}`,
      `Fork session: ${data.fork_session_id}`,
      `Substituted event: #${data.substitution.seq} ${JSON.stringify(data.substitution.result)}`,
      "",
      `Baseline outcome: ${JSON.stringify(data.outcomes.baseline)}`,
      `Strict replay outcome: ${JSON.stringify(data.outcomes.strict_replay)}`,
      `Forked outcome: ${JSON.stringify(data.outcomes.forked)}`,
      "",
      `Changed events: ${data.events.changed.length}`,
      `Added events: ${data.events.added.length}`,
      `Removed events: ${data.events.removed.length}`,
      `Event-count delta: ${data.metrics.event_count_delta}`,
      `Duration delta: ${data.metrics.duration_ms.delta} ms (${data.metrics.duration_ms.label})`,
      data.metrics.tokens.available
        ? `Token delta: ${data.metrics.tokens.forked_in - data.metrics.tokens.baseline_in} in / ${data.metrics.tokens.forked_out - data.metrics.tokens.baseline_out} out`
        : "Tokens: unavailable; no comparable model usage was recorded.",
      data.metrics.cost_usd_estimate.available
        ? `Estimated cost delta: $${data.metrics.cost_usd_estimate.delta}`
        : "Estimated cost: unavailable; no comparable model usage was recorded.",
      "",
      "Event differences:",
      JSON.stringify(
        { changed: data.events.changed, added: data.events.added, removed: data.events.removed },
        null,
        2
      ),
    ].join("\n");
    experimentResultsEl.appendChild(summary);

    [data.parent_session_id, data.fork_session_id].forEach(sessionId => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-secondary";
      button.textContent = `View ${sessionId}`;
      button.addEventListener("click", async () => {
        await fetchSessions();
        await selectSession(sessionId);
        switchTab("timeline");
      });
      experimentResultsEl.appendChild(button);
    });
  }

  async function runExperiment() {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 30000);
    try {
      runExperimentBtn.disabled = true;
      experimentResultsEl.textContent = "Running deterministic experiment...";
      const res = await fetch("/api/experiments/counterfactual", {
        method: "POST",
        signal: controller.signal,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Experiment failed");
      renderExperiment(data);
      await fetchSessions();
    } catch (err) {
      const message =
        err.name === "AbortError" ? "The experiment timed out." : err.message;
      experimentResultsEl.textContent = `Experiment failed: ${message}`;
    } finally {
      window.clearTimeout(timeoutId);
      runExperimentBtn.disabled = false;
    }
  }

  async function fetchSessions() {
    try {
      sessionsListEl.textContent = "Loading sessions...";
      const res = await fetch("/api/sessions");
      if (!res.ok) throw new Error("Failed to load sessions");
      allSessions = await res.json();
      sessionCountBadge.textContent = `${allSessions.length} Sessions`;
      populateReplaySessions(allSessions);
      renderSessionsList(allSessions);
    } catch (err) {
      sessionsListEl.textContent = `Error: ${err.message}`;
    }
  }

  function renderSessionsList(sessions) {
    sessionsListEl.replaceChildren();
    if (!sessions.length) {
      sessionsListEl.textContent = "No recorded sessions yet.";
      return;
    }

    sessions.forEach(sess => {
      const item = document.createElement("div");
      item.className = `session-item ${currentSessionData && currentSessionData.session_id === sess.session_id ? 'active' : ''}`;

      const dateStr = sess.started_at ? new Date(sess.started_at).toLocaleTimeString() : "";
      const header = document.createElement("div");
      header.className = "session-item-header";
      const sessionId = document.createElement("span");
      sessionId.className = "session-id";
      sessionId.textContent = sess.session_id;
      header.appendChild(sessionId);
      if (sess.has_errors) {
        const errorTag = document.createElement("span");
        errorTag.className = "badge session-error-badge";
        errorTag.textContent = "Error";
        header.appendChild(errorTag);
      }

      const footer = document.createElement("div");
      footer.className = "session-item-footer";
      const eventMeta = document.createElement("span");
      eventMeta.textContent = `${sess.event_count} events · ${dateStr}`;
      const cost = document.createElement("span");
      cost.className = "cost-pill";
      cost.textContent = `$${Number(sess.total_cost_usd || 0).toFixed(6)}`;
      footer.append(eventMeta, cost);
      item.append(header, footer);

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
      replaySessionSelect.value = sessionId;

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
    metricCost.textContent = data.metrics_available?.cost
      ? `$${Number(data.total_cost_usd).toFixed(6)}`
      : "N/A";
    metricDuration.textContent = data.total_duration_ms != null
      ? `${data.total_duration_ms} ms`
      : "N/A";
    metricEvents.textContent = `${data.event_count} (${data.tool_calls_count} tools, ${data.model_calls_count} models)`;
    metricOutcomes.textContent = `${data.successful_events} / ${data.failed_events}`;
    metricSlowest.textContent = data.slowest_event
      ? `#${data.slowest_event.seq} ${data.slowest_event.name} (${data.slowest_event.duration_ms} ms)`
      : "N/A";
    renderToolStats(data.tool_stats || {});
  }

  function renderToolStats(stats) {
    toolStatsEl.replaceChildren();
    const entries = Object.entries(stats);
    if (!entries.length) {
      toolStatsEl.textContent = "No tool calls recorded.";
      return;
    }
    entries.forEach(([name, values]) => {
      const item = document.createElement("span");
      item.className = "tool-stat";
      item.textContent = `${name}: ${values.event_count} calls, ${values.failure_count} failed`;
      toolStatsEl.appendChild(item);
    });
  }

  function renderFlags(flags) {
    if (!flagsContainerEl) return;
    flagsContainerEl.replaceChildren();
    if (!flags.length) {
      flagsContainerEl.classList.add("hidden");
      return;
    }

    flagsContainerEl.classList.remove("hidden");
    flags.forEach(flag => {
      const banner = document.createElement("div");
      banner.className = `flag-banner ${flag.severity}`;
      const icon = flag.severity === "danger" ? "🚨" : "⚠️";
      const iconEl = document.createElement("span");
      iconEl.textContent = icon;
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = `${flag.rule_name.replace(/_/g, " ").toUpperCase()}:`;
      content.append(title, document.createTextNode(` ${flag.message}`));
      banner.append(iconEl, content);
      flagsContainerEl.appendChild(banner);
    });
  }

  function renderTimeline(events, flags = []) {
    timelineEventsEl.replaceChildren();
    const culpritSeqs = new Set();
    flags.forEach(f => (f.culprit_seqs || []).forEach(s => culpritSeqs.add(s)));
    const maxDuration = Math.max(...events.map(e => Number(e.duration_ms) || 0), 0);

    const filtered = events.filter(e => {
      if (currentFilter === "all") return true;
      return e.type === currentFilter;
    }).filter(e => {
      const status = eventStatusFilter.value;
      const query = eventSearchInput.value.trim().toLowerCase();
      return (status === "all" || e.status === status)
        && (!query || `${e.name} ${e.type}`.toLowerCase().includes(query));
    });

    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.style.height = "150px";
      empty.textContent = "No events match filter.";
      timelineEventsEl.appendChild(empty);
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

      const node = document.createElement("div");
      node.className = "timeline-node-dot";
      const header = document.createElement("div");
      header.className = "card-header";
      const titleGroup = document.createElement("div");
      titleGroup.className = "card-title-group";
      const seq = document.createElement("span");
      seq.className = "seq-badge";
      seq.textContent = `#${e.seq}`;
      const type = document.createElement("span");
      type.className = `type-pill ${e.type}`;
      type.textContent = e.type === "tool_call" ? "Tool" : "Model";
      const name = document.createElement("span");
      name.className = "event-name";
      name.textContent = e.name;
      titleGroup.append(seq, type, name);
      const status = document.createElement("span");
      status.className = `status-pill ${e.status || (e.error ? "failed" : "success")}`;
      status.textContent = e.status || (e.error ? "failed" : "success");
      titleGroup.appendChild(status);
      if (isCulprit) {
        const culprit = document.createElement("span");
        culprit.className = "flag-pill";
        culprit.textContent = "Flagged";
        titleGroup.appendChild(culprit);
      }
      const metaGroup = document.createElement("div");
      metaGroup.className = "card-meta-group";
      if (e.type === "model_call") {
        const tokens = document.createElement("span");
        tokens.textContent = `Tokens: ${e.tokens_in} in / ${e.tokens_out} out`;
        metaGroup.appendChild(tokens);
      }
      const duration = document.createElement("span");
      duration.textContent = `⏱️ ${e.duration_ms}ms`;
      const durationTrack = document.createElement("span");
      durationTrack.className = "duration-track";
      const durationBar = document.createElement("span");
      durationBar.className = "duration-bar";
      durationBar.style.width = `${maxDuration ? Math.max(4, (e.duration_ms / maxDuration) * 100) : 4}%`;
      durationTrack.appendChild(durationBar);
      const cost = document.createElement("span");
      cost.className = "cost-pill";
      cost.textContent = `$${Number(e.cost_usd || 0).toFixed(6)}`;
      metaGroup.append(duration, durationTrack, cost);
      header.append(titleGroup, metaGroup);
      card.append(node, header);

      if (e.error) {
        const errorBlock = document.createElement("div");
        errorBlock.className = "error-banner";
        const errorTitle = document.createElement("strong");
        errorTitle.textContent = "Error:";
        errorBlock.append(errorTitle, document.createTextNode(` ${e.error}`));
        card.appendChild(errorBlock);
      }
      if (e.error_type) {
        const errorType = document.createElement("div");
        errorType.className = "error-type";
        errorType.textContent = `Exception type: ${e.error_type}`;
        card.appendChild(errorType);
      }

      const addAccordion = (label, value) => {
        const section = document.createElement("div");
        section.className = "accordion-section";
        const toggle = document.createElement("button");
        toggle.className = "accordion-toggle";
        toggle.type = "button";
        toggle.textContent = `▶ ${label}`;
        const code = document.createElement("pre");
        code.className = "code-block hidden";
        code.textContent = value;
        toggle.addEventListener("click", () => code.classList.toggle("hidden"));
        section.append(toggle, code);
        card.appendChild(section);
      };
      addAccordion("Arguments & Inputs", argsPretty);
      addAccordion("Result & Outputs", resultPretty);

      timelineEventsEl.appendChild(card);
    });
  }

  async function fetchLiveScenarios() {
    if (!liveScenarioSelect) return;
    try {
      const res = await fetch("/api/live/scenarios");
      if (!res.ok) throw new Error("Failed to load live scenarios");
      const scenarios = await res.json();
      liveScenarioSelect.replaceChildren();
      Object.entries(scenarios).forEach(([id, details]) => {
        const option = document.createElement("option");
        option.value = id;
        option.textContent = `${details.label} — ${details.description} (${details.expected_duration})`;
        liveScenarioSelect.appendChild(option);
      });
    } catch (err) {
      liveScenarioSelect.replaceChildren();
      const errOpt = document.createElement("option");
      errOpt.textContent = `Error loading scenarios: ${err.message}`;
      liveScenarioSelect.appendChild(errOpt);
    }
  }

  async function runLiveScenario() {
    if (!liveScenarioSelect || !liveScenarioSelect.value) return;
    const scenarioId = liveScenarioSelect.value;
    try {
      runLiveBtn.disabled = true;
      liveScenarioSelect.disabled = true;

      liveRunStatusEl.className = "live-run-status running";
      liveRunStatusEl.replaceChildren();
      const statusText = document.createElement("span");
      statusText.textContent = "⚡ Running live scenario...";
      liveRunStatusEl.appendChild(statusText);
      liveRunStatusEl.classList.remove("hidden");

      const res = await fetch("/api/live/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: scenarioId }),
      });
      const data = await res.json();

      liveRunStatusEl.replaceChildren();
      const msgSpan = document.createElement("span");

      if (res.ok && (data.status === "done" || data.status === "step_limit_reached")) {
        liveRunStatusEl.className = "live-run-status done";
        msgSpan.textContent = `Done - ${data.event_count} events, cost Rs. ${data.total_cost_inr}`;
      } else if (res.ok && data.status === "timed_out") {
        liveRunStatusEl.className = "live-run-status timed_out";
        msgSpan.textContent = `Timed out after ${data.event_count} events - partial session saved`;
      } else {
        liveRunStatusEl.className = "live-run-status error";
        msgSpan.textContent = `Run failed: ${data.detail || data.message || "Unknown error"}`;
      }
      liveRunStatusEl.appendChild(msgSpan);

      if (data.session_id) {
        const linkBtn = document.createElement("button");
        linkBtn.type = "button";
        linkBtn.className = "btn-link";
        linkBtn.textContent = `View timeline (${data.session_id}) →`;
        linkBtn.addEventListener("click", async () => {
          await fetchSessions();
          await selectSession(data.session_id);
          switchTab("timeline");
        });
        liveRunStatusEl.appendChild(linkBtn);
      }

      await fetchSessions();
    } catch (err) {
      liveRunStatusEl.className = "live-run-status error";
      liveRunStatusEl.replaceChildren();
      const errSpan = document.createElement("span");
      errSpan.textContent = `Error: ${err.message}`;
      liveRunStatusEl.appendChild(errSpan);
    } finally {
      runLiveBtn.disabled = false;
      liveScenarioSelect.disabled = false;
    }
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
  eventSearchInput.addEventListener("input", () => {
    if (currentSessionData) renderTimeline(currentSessionData.events || [], currentSessionData.flags || []);
  });
  eventStatusFilter.addEventListener("change", () => {
    if (currentSessionData) renderTimeline(currentSessionData.events || [], currentSessionData.flags || []);
  });

  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  runReplayBtn.addEventListener("click", () => runReplay());
  [usageProviderFilter, usageModelFilter, usageSessionFilter].forEach(filter => {
    filter.addEventListener("change", () => {
      if (document.querySelector('[data-panel="cost"]').classList.contains("active")) {
        switchTab("cost");
      }
    });
  });
  if (runExperimentBtn) {
    runExperimentBtn.addEventListener("click", runExperiment);
  }
  savePricingBtn.addEventListener("click", savePricing);
  saveDetectorBtn.addEventListener("click", saveDetectorConfig);
  if (runLiveBtn) {
    runLiveBtn.addEventListener("click", runLiveScenario);
  }

  fetchSessions();
  switchTab(window.localStorage.getItem("agent-replay-section") || "overview");
});