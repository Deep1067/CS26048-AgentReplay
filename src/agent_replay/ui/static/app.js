document.addEventListener("DOMContentLoaded", () => {
  let allSessions = [];
  let currentSessionData = null;
  let currentExperimentId = null;
  let currentEvaluationSuite = null;
  let evaluationSuites = [];
  let latestEvaluationSuites = [];
  let loadExperimentEvaluations = null;
  let loadSessionEvaluationHistory = null;
  let currentFilter = "all";
  let liveMonitorTimer = null;
  let liveExecutionEnabled = false;

  const sessionSearchInput = document.getElementById("session-search");
  const sessionsListEl = document.getElementById("sessions-list");
  const refreshBtn = document.getElementById("refresh-btn");
  const sessionCountBadge = document.getElementById("session-count-badge");
  const sessionContext = document.getElementById("session-context");
  const sessionsSidebar = document.getElementById("sessions-sidebar");

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
  const replayValidationHistoryEl = document.getElementById("replay-validation-history");
  const runExperimentBtn = document.getElementById("run-experiment-btn");
  const experimentResultsEl = document.getElementById("experiment-results");
  const experimentBaselineSelect = document.getElementById("experiment-baseline-select");
  const experimentEventSelect = document.getElementById("experiment-event-select");
  const experimentResultInput = document.getElementById("experiment-result-input");
  const experimentHistoryEl = document.getElementById("experiment-history");
  const experimentEvaluationCriteria = document.getElementById("experiment-evaluation-criteria");
  const evaluateExperimentBtn = document.getElementById("evaluate-experiment-btn");
  const experimentEvaluationResults = document.getElementById("experiment-evaluation-results");
  const experimentEvaluationHistory = document.getElementById("experiment-evaluation-history");
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
  const liveCapabilityStatus = document.getElementById("live-capability-status");
  const liveRecentSessions = document.getElementById("live-recent-sessions");

  const filterBtns = document.querySelectorAll(".filter-btn");
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");
  const sidebarLinks = document.querySelectorAll(".sidebar-link");
  const sidebar = document.getElementById("app-sidebar");
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const mobileNavToggle = document.getElementById("mobile-nav-toggle");
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
  const playgroundEvaluationSession = document.getElementById("playground-evaluation-session");
  const playgroundEvaluationCriteria = document.getElementById("playground-evaluation-criteria");
  const evaluateRecordedSessionBtn = document.getElementById("evaluate-recorded-session-btn");
  const playgroundEvaluationResults = document.getElementById("playground-evaluation-results");
  const playgroundEvaluationHistory = document.getElementById("playground-evaluation-history");
  const playgroundEvaluationSuite = document.getElementById("playground-evaluation-suite");
  const experimentSuiteSelect = document.getElementById("experiment-suite-select");
  const suiteTemplateSelect = document.getElementById("suite-template-select");
  const suiteEditSelect = document.getElementById("suite-edit-select");
  const suiteNameInput = document.getElementById("suite-name-input");
  const suiteDescriptionInput = document.getElementById("suite-description-input");
  const suiteCriteriaInput = document.getElementById("suite-criteria-input");
  const saveSuiteBtn = document.getElementById("save-suite-btn");
  const suiteLibraryStatus = document.getElementById("suite-library-status");
  const suiteLibraryHistory = document.getElementById("suite-library-history");
  const usageProviderFilter = document.getElementById("usage-provider-filter");
  const usageModelFilter = document.getElementById("usage-model-filter");
  const usageSessionFilter = document.getElementById("usage-session-filter");
  const usageTableBody = document.getElementById("usage-table-body");

  function formatCost(value, status) {
    if (status === "unavailable" || value == null) return "Unavailable";
    const prefix = status === "estimated" ? "≈ " : "";
    return `${prefix}$${Number(value).toFixed(8)} (${status})`;
  }

  function populateEvaluationSessions(sessions) {
    const selected = currentSessionData?.session_id || playgroundEvaluationSession.value;
    playgroundEvaluationSession.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Choose a recorded session";
    playgroundEvaluationSession.appendChild(placeholder);
    sessions.forEach(session => {
      const option = document.createElement("option");
      option.value = session.session_id;
      option.textContent = `${session.session_id} · ${session.event_count} events`;
      playgroundEvaluationSession.appendChild(option);
    });
    if ([...playgroundEvaluationSession.options].some(option => option.value === selected)) {
      playgroundEvaluationSession.value = selected;
    }
  }

  function switchTab(tabName) {
    const validTabs = new Set(["overview", "timeline", "replay", "experiment", "live", "cost", "detector", "playground"]);
    if (!validTabs.has(tabName)) tabName = "overview";
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
    sessionsSidebar.classList.toggle("hidden", tabName !== "timeline");
    sessionContext.textContent = currentSessionData
      ? `Session: ${currentSessionData.session_id}`
      : "No session selected";
    sessionContext.disabled = !currentSessionData;
    window.localStorage.setItem("agent-replay-section", tabName);
    if (window.matchMedia("(max-width: 850px)").matches) {
      sidebar.classList.remove("mobile-open");
      sidebarOverlay.hidden = true;
      mobileNavToggle.setAttribute("aria-expanded", "false");
      mobileNavToggle.setAttribute("aria-label", "Open navigation");
    }

    function addListenerOnce(element, key, eventName, listener) {
      if (element.dataset[key] === "true") return;
      element.dataset[key] = "true";
      element.addEventListener(eventName, listener);
    }

    function parseEvaluationCriteria(input) {
      let criteria;
      try {
        criteria = JSON.parse(input.value);
      } catch (_) {
        throw new Error("Evaluation criteria must be valid JSON.");
      }
      if (!criteria || typeof criteria !== "object" || Array.isArray(criteria)) {
        throw new Error("Evaluation criteria must be a JSON object.");
      }
      return criteria;
    }

    function setSuiteOptions(select, suites) {
      const selected = select.value;
      select.replaceChildren();
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "Use criteria editor instead";
      select.appendChild(empty);
      suites.forEach(suite => {
        const option = document.createElement("option");
        option.value = `${suite.suite_id}|${suite.version}`;
        option.textContent = `${suite.name} · v${suite.version}`;
        select.appendChild(option);
      });
      if ([...select.options].some(option => option.value === selected)) {
        select.value = selected;
      }
    }

    async function fetchEvaluationSuites() {
      try {
        const [suitesResponse, templatesResponse] = await Promise.all([
          fetch("/api/evaluation-suites"),
          fetch("/api/evaluation-suites/templates"),
        ]);
        const suitesData = await suitesResponse.json();
        const templatesData = await templatesResponse.json();
        if (!suitesResponse.ok) throw new Error(suitesData.detail || "Unable to load suites.");
        if (!templatesResponse.ok) throw new Error(templatesData.detail || "Unable to load templates.");
        latestEvaluationSuites = suitesData.suites;
        const versionLists = await Promise.all(
          latestEvaluationSuites.map(async suite => {
            const response = await fetch(
              `/api/evaluation-suites/${encodeURIComponent(suite.suite_id)}/versions`
            );
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "Unable to load suite versions.");
            return data.versions;
          })
        );
        evaluationSuites = versionLists.flat();
        setSuiteOptions(playgroundEvaluationSuite, evaluationSuites);
        setSuiteOptions(experimentSuiteSelect, evaluationSuites);
        const selectedSuiteId = suiteEditSelect.value;
        suiteEditSelect.replaceChildren();
        const empty = document.createElement("option");
        empty.value = "";
        empty.textContent = "Create a new suite";
        suiteEditSelect.appendChild(empty);
        latestEvaluationSuites.forEach(suite => {
          const option = document.createElement("option");
          option.value = suite.suite_id;
          option.textContent = `${suite.name} · v${suite.version}`;
          suiteEditSelect.appendChild(option);
        });
        if ([...suiteEditSelect.options].some(option => option.value === selectedSuiteId)) {
          suiteEditSelect.value = selectedSuiteId;
        }
        suiteTemplateSelect.replaceChildren();
        const templatePlaceholder = document.createElement("option");
        templatePlaceholder.value = "";
        templatePlaceholder.textContent = "Choose a template";
        suiteTemplateSelect.appendChild(templatePlaceholder);
        templatesData.templates.forEach(template => {
          const option = document.createElement("option");
          option.value = template.id;
          option.textContent = template.name;
          suiteTemplateSelect.appendChild(option);
        });
      } catch (err) {
        suiteLibraryStatus.textContent = `Unable to load evaluation suites: ${err.message}`;
      }
    }

    function populateSuiteForm(suite) {
      currentEvaluationSuite = suite;
      suiteNameInput.value = suite?.name || "";
      suiteDescriptionInput.value = suite?.description || "";
      suiteCriteriaInput.value = JSON.stringify(
        suite?.criteria || { expected_output: { answer: "expected value" } },
        null,
        2
      );
      saveSuiteBtn.textContent = suite ? `Save as version ${suite.version + 1}` : "Create suite";
    }

    addListenerOnce(suiteTemplateSelect, "templateListener", "change", async () => {
      if (!suiteTemplateSelect.value) return;
      try {
        const response = await fetch("/api/evaluation-suites/templates");
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Unable to load templates.");
        const template = data.templates.find(item => item.id === suiteTemplateSelect.value);
        if (!template) throw new Error("The selected template is no longer available.");
        suiteEditSelect.value = "";
        populateSuiteForm({
          name: template.name,
          description: template.description,
          criteria: template.criteria,
        });
        currentEvaluationSuite = null;
        saveSuiteBtn.textContent = "Create suite from template";
        suiteLibraryHistory.replaceChildren();
      } catch (err) {
        suiteLibraryStatus.textContent = err.message;
      }
    });

    addListenerOnce(suiteEditSelect, "editListener", "change", async () => {
      if (!suiteEditSelect.value) {
        populateSuiteForm(null);
        suiteLibraryHistory.textContent = "Select a saved suite or choose a template.";
        return;
      }
      try {
        const response = await fetch(
          `/api/evaluation-suites/${encodeURIComponent(suiteEditSelect.value)}`
        );
        const suite = await response.json();
        if (!response.ok) throw new Error(suite.detail || "Unable to load suite.");
        populateSuiteForm(suite);
        await fetchEvaluationSuiteVersions(suite.suite_id, suite.version);
      } catch (err) {
        suiteLibraryStatus.textContent = err.message;
      }
    });

    async function fetchEvaluationSuiteVersions(suiteId, latestVersion) {
      try {
        const response = await fetch(
          `/api/evaluation-suites/${encodeURIComponent(suiteId)}/versions`
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Unable to load suite versions.");
        suiteLibraryHistory.replaceChildren();
        data.versions.forEach(suite => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "overview-session";
          button.textContent = `${suite.name} · version ${suite.version}${suite.version === latestVersion ? " (current)" : " (history)"}`;
          button.addEventListener("click", () => populateSuiteForm(suite));
          suiteLibraryHistory.appendChild(button);
        });
      } catch (err) {
        suiteLibraryHistory.textContent = `Unable to load suite versions: ${err.message}`;
      }
    }

    addListenerOnce(saveSuiteBtn, "saveListener", "click", async () => {
      let criteria;
      try {
        criteria = parseEvaluationCriteria(suiteCriteriaInput);
      } catch (err) {
        suiteLibraryStatus.textContent = err.message;
        return;
      }
      const body = {
        name: suiteNameInput.value,
        description: suiteDescriptionInput.value,
        criteria,
      };
      const editing = currentEvaluationSuite?.suite_id;
      if (
        editing &&
        latestEvaluationSuites.find(item => item.suite_id === editing)?.version !== currentEvaluationSuite.version
      ) {
        suiteLibraryStatus.textContent =
          "Historical suite versions are read-only. Select the current version before editing.";
        return;
      }
      if (editing) body.current_version = currentEvaluationSuite.version;
      saveSuiteBtn.disabled = true;
      try {
        const response = await fetch(
          editing
            ? `/api/evaluation-suites/${encodeURIComponent(editing)}`
            : "/api/evaluation-suites",
          {
            method: editing ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        );
        const suite = await response.json();
        if (!response.ok) throw new Error(suite.detail || "Unable to save suite.");
        await fetchEvaluationSuites();
        suiteEditSelect.value = suite.suite_id;
        populateSuiteForm(suite);
        await fetchEvaluationSuiteVersions(suite.suite_id, suite.version);
        suiteLibraryStatus.textContent = `Saved ${suite.name} version ${suite.version}.`;
      } catch (err) {
        suiteLibraryStatus.textContent = `Unable to save suite: ${err.message}`;
      } finally {
        saveSuiteBtn.disabled = false;
      }
    });

    function selectedSuite(select) {
      if (!select.value) return null;
      const [suiteId, rawVersion] = select.value.split("|");
      const version = Number(rawVersion);
      return evaluationSuites.find(
        suite => suite.suite_id === suiteId && suite.version === version
      ) || null;
    }

    addListenerOnce(playgroundEvaluationSuite, "suiteListener", "change", () => {
      const suite = selectedSuite(playgroundEvaluationSuite);
      playgroundEvaluationCriteria.readOnly = Boolean(suite);
      if (suite) playgroundEvaluationCriteria.value = JSON.stringify(suite.criteria, null, 2);
    });

    addListenerOnce(experimentSuiteSelect, "suiteListener", "change", () => {
      const suite = selectedSuite(experimentSuiteSelect);
      experimentEvaluationCriteria.readOnly = Boolean(suite);
      if (suite) experimentEvaluationCriteria.value = JSON.stringify(suite.criteria, null, 2);
    });

    function renderEvaluation(container, record) {
      const result = record.result || {};
      const heading = document.createElement("h3");
      heading.className = "section-heading";
      heading.textContent = `Evaluation ${record.evaluation_id || ""} · ${result.status || "unknown"}`;
      const metadata = document.createElement("p");
      metadata.className = "text-muted";
      metadata.textContent = [
        `Recorded ${record.evaluated_at || result.evaluated_at || "time unavailable"}`,
        record.suite_id ? `Suite ${record.suite_id} version ${record.suite_version}` : "Inline criteria",
        "Deterministic evaluation of recorded evidence; not a guarantee of correctness.",
      ].join(" · ");
      const content = document.createElement("div");
      if (result.baseline && result.fork) {
        const comparison = document.createElement("p");
        comparison.textContent =
          `Baseline: ${result.baseline.status}; fork: ${result.fork.status}. ` +
          "Replay validity is reported separately from these quality results.";
        content.appendChild(comparison);
        const table = document.createElement("table");
        table.className = "pricing-table";
        const head = document.createElement("thead");
        const headerRow = document.createElement("tr");
        ["Check", "Baseline", "Fork"].forEach(label => {
          const cell = document.createElement("th");
          cell.textContent = label;
          headerRow.appendChild(cell);
        });
        head.appendChild(headerRow);
        const body = document.createElement("tbody");
        Object.entries(result.comparison?.criteria_statuses || {}).forEach(([name, statuses]) => {
          const row = document.createElement("tr");
          [name, statuses.baseline, statuses.fork].forEach(value => {
            const cell = document.createElement("td");
            cell.textContent = value || "unavailable";
            row.appendChild(cell);
          });
          body.appendChild(row);
        });
        table.append(head, body);
        content.appendChild(table);
        if (result.comparison) {
          const changes = document.createElement("p");
          changes.textContent =
            `Improvements: ${(result.comparison.improvements || []).join(", ") || "none"}; ` +
            `regressions: ${(result.comparison.regressions || []).join(", ") || "none"}; ` +
            `unchanged: ${(result.comparison.unchanged || []).join(", ") || "none"}; ` +
            `not comparable: ${(result.comparison.not_comparable || []).join(", ") || "none"}.`;
          content.appendChild(changes);
        }
      } else {
        const status = document.createElement("p");
        status.textContent = result.status_explanation || result.explanation || "No evaluation explanation is available.";
        content.appendChild(status);
        const evaluators = document.createElement("ul");
        Object.entries(result.evaluators || {}).forEach(([name, evaluator]) => {
          const item = document.createElement("li");
          item.textContent = `${evaluator.name || name}: ${evaluator.status} — ${evaluator.explanation}`;
          evaluators.appendChild(item);
        });
        content.appendChild(evaluators);
      }
      const evidence = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Criteria, evidence, and full evaluation record";
      const output = document.createElement("pre");
      output.className = "code-block";
      output.textContent = JSON.stringify(record, null, 2);
      evidence.append(summary, output);
      container.replaceChildren(heading, metadata, content, evidence);
    }

    async function fetchExperimentEvaluations(experimentId) {
      try {
        const response = await fetch(
          `/api/experiments/${encodeURIComponent(experimentId)}/evaluations`
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Unable to load evaluation history.");
        experimentEvaluationHistory.replaceChildren();
        if (!data.evaluations.length) {
          experimentEvaluationHistory.textContent = "No evaluations saved for this comparison.";
          return;
        }
        data.evaluations.forEach(record => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "overview-session";
          button.textContent = `${record.evaluated_at} · ${record.result.status}${record.suite_id ? ` · ${record.suite_id} v${record.suite_version}` : ""}`;
          button.addEventListener("click", async () => {
            if (record.suite_id) await fetchEvaluationSuites();
            experimentEvaluationCriteria.value = JSON.stringify(record.criteria, null, 2);
            experimentSuiteSelect.value = record.suite_id
              ? `${record.suite_id}|${record.suite_version}`
              : "";
            experimentEvaluationCriteria.readOnly = Boolean(record.suite_id);
            renderEvaluation(experimentEvaluationResults, record);
          });
          experimentEvaluationHistory.appendChild(button);
        });
      } catch (err) {
        experimentEvaluationHistory.textContent = `Unable to load evaluation history: ${err.message}`;
      }
    }

    loadExperimentEvaluations = fetchExperimentEvaluations;

    addListenerOnce(evaluateExperimentBtn, "evaluateListener", "click", async () => {
      if (!currentExperimentId) return;
      evaluateExperimentBtn.disabled = true;
      try {
        const suite = selectedSuite(experimentSuiteSelect);
        const evaluation = suite
          ? { suite_id: suite.suite_id, suite_version: suite.version }
          : { criteria: parseEvaluationCriteria(experimentEvaluationCriteria) };
        experimentEvaluationResults.textContent = "Evaluating the recorded baseline and fork...";
        const response = await fetch(
          `/api/experiments/${encodeURIComponent(currentExperimentId)}/evaluations`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(evaluation),
          }
        );
        const record = await response.json();
        if (!response.ok) throw new Error(record.detail || "Evaluation failed.");
        renderEvaluation(experimentEvaluationResults, record);
        await fetchExperimentEvaluations(currentExperimentId);
      } catch (err) {
        experimentEvaluationResults.textContent = `Evaluation failed: ${err.message}`;
      } finally {
        evaluateExperimentBtn.disabled = !currentExperimentId;
      }
    });

    addListenerOnce(evaluateRecordedSessionBtn, "evaluateListener", "click", async () => {
      const sessionId = playgroundEvaluationSession.value;
      if (!sessionId) {
        playgroundEvaluationResults.textContent = "Select a recorded session to evaluate.";
        return;
      }
      evaluateRecordedSessionBtn.disabled = true;
      try {
        const suite = selectedSuite(playgroundEvaluationSuite);
        const evaluation = suite
          ? { suite_id: suite.suite_id, suite_version: suite.version }
          : { criteria: parseEvaluationCriteria(playgroundEvaluationCriteria) };
        playgroundEvaluationResults.textContent = "Evaluating the recorded output; no provider call will be made...";
        const response = await fetch(
          `/api/evaluations/sessions/${encodeURIComponent(sessionId)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(evaluation),
          }
        );
        const record = await response.json();
        if (!response.ok) throw new Error(record.detail || "Evaluation failed.");
        renderEvaluation(playgroundEvaluationResults, record);
        await fetchSessionEvaluationHistory(sessionId);
      } catch (err) {
        playgroundEvaluationResults.textContent = `Evaluation failed: ${err.message}`;
      } finally {
        evaluateRecordedSessionBtn.disabled = false;
      }
    });

    async function fetchSessionEvaluationHistory(sessionId) {
      playgroundEvaluationHistory.replaceChildren();
      if (!sessionId) {
        playgroundEvaluationHistory.textContent = "Select a session to view saved evaluations.";
        return;
      }
      try {
        const response = await fetch(
          `/api/evaluations?session_id=${encodeURIComponent(sessionId)}`
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Unable to load session evaluations.");
        if (!data.evaluations.length) {
          playgroundEvaluationHistory.textContent = "No saved evaluations for this session.";
          return;
        }
        data.evaluations.forEach(record => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "overview-session";
          button.textContent = `${record.evaluated_at} · ${record.result.status}${record.suite_id ? ` · ${record.suite_id} v${record.suite_version}` : ""}`;
          button.addEventListener("click", async () => {
            if (record.suite_id) await fetchEvaluationSuites();
            playgroundEvaluationCriteria.value = JSON.stringify(record.criteria, null, 2);
            playgroundEvaluationSuite.value = record.suite_id
              ? `${record.suite_id}|${record.suite_version}`
              : "";
            playgroundEvaluationCriteria.readOnly = Boolean(record.suite_id);
            renderEvaluation(playgroundEvaluationResults, record);
          });
          playgroundEvaluationHistory.appendChild(button);
        });
      } catch (err) {
        playgroundEvaluationHistory.textContent = `Unable to load evaluation history: ${err.message}`;
      }
    }

    loadSessionEvaluationHistory = fetchSessionEvaluationHistory;

    addListenerOnce(playgroundEvaluationSession, "historyListener", "change", () => {
      fetchSessionEvaluationHistory(playgroundEvaluationSession.value);
    });
    if (tabName === "overview") fetchOverview();
    if (tabName === "playground") fetchProviders();
    if (tabName === "playground") fetchEvaluationSuites();
    if (tabName === "experiment") {
      fetchEvaluationSuites();
      fetchExperimentBaselines();
      fetchExperimentHistory();
    }
    if (tabName === "cost") {
      fetchPricing();
      fetchCostHistory();
      if (currentSessionData && !usageSessionFilter.value) {
        if (![...usageSessionFilter.options].some(option => option.value === currentSessionData.session_id)) {
          const option = document.createElement("option");
          option.value = currentSessionData.session_id;
          option.textContent = currentSessionData.session_id;
          usageSessionFilter.appendChild(option);
        }
        usageSessionFilter.value = currentSessionData.session_id;
      }
      fetchUsage();
    }
    if (tabName === "live") {
      fetchLiveScenarios();
      refreshLiveMonitor();
      if (liveMonitorTimer === null) {
        liveMonitorTimer = window.setInterval(refreshLiveMonitor, 5000);
      }
    } else if (liveMonitorTimer !== null) {
      window.clearInterval(liveMonitorTimer);
      liveMonitorTimer = null;
    }
    if (tabName === "detector") fetchDetectorConfig();
  }

  async function fetchUsage() {
      const summary = document.getElementById("usage-summary");
      try {
        const params = new URLSearchParams();
        if (usageProviderFilter.value) params.set("provider", usageProviderFilter.value);
        if (usageModelFilter.value) params.set("model", usageModelFilter.value);
        if (usageSessionFilter.value) params.set("session_id", usageSessionFilter.value);
        const response = await fetch(`/api/usage?${params}`);
        if (!response.ok) throw new Error("Failed to load model usage.");
        const data = await response.json();
        if (!usageProviderFilter.dataset.loaded) {
          let filterData = data;
          if (params.toString()) {
            const allResponse = await fetch("/api/usage");
            if (!allResponse.ok) throw new Error("Failed to load usage filter options.");
            filterData = await allResponse.json();
          }
          const providers = [...new Set(filterData.records.map(record => record.provider))].sort();
          const models = [...new Set(filterData.records.map(record => record.model))].sort();
          const sessions = [...new Set(filterData.records.map(record => record.session_id))].sort();
          for (const [select, values] of [
            [usageProviderFilter, providers],
            [usageModelFilter, models],
            [usageSessionFilter, sessions],
          ]) {
            values.forEach(value => {
              const option = document.createElement("option");
              option.value = value;
              option.textContent = value;
              select.appendChild(option);
            });
          }
          usageProviderFilter.dataset.loaded = "true";
        }
        summary.replaceChildren();
        if (!data.groups.length) {
          summary.textContent = "No recorded model usage is available for these filters. Configure a provider and submit a Playground request, or select a session with model calls.";
          usageTableBody.replaceChildren();
          return;
  }
        usageTableBody.replaceChildren();
        (data.records || []).forEach(record => {
          const tableRow = document.createElement("tr");
          const cost = formatCost(record.cost_usd, record.cost_status);
          [
            `${record.provider} / ${record.model}`,
            record.session_id,
            record.event_count,
            record.usage_available ? record.input_tokens : "Unavailable",
            record.usage_available ? record.output_tokens : "Unavailable",
            cost,
          ].forEach(value => {
            const cell = document.createElement("td");
            cell.textContent = String(value);
            tableRow.appendChild(cell);
          });
          usageTableBody.appendChild(tableRow);
          const row = document.createElement("div");
          row.className = "usage-row";
          row.textContent = `${record.session_id} · ${record.provider} / ${record.model} · ${
            record.usage_available
              ? `${record.input_tokens} in · ${record.output_tokens} out`
              : "token usage unavailable"
          } · ${cost}`;
          summary.appendChild(row);
        });
      } catch (err) {
        summary.textContent = `Unable to load model usage: ${err.message}`;
      }
    }

  async function fetchOverview() {
      try {
        const response = await fetch("/api/overview");
        if (!response.ok) throw new Error("Failed to load overview.");
        const data = await response.json();
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
        assistant.textContent = `${data.text}\n\nSource: ${data.output_source} · Session: ${data.session_id}\nUsage: ${data.usage ? JSON.stringify(data.usage) : "Unavailable"} · Cost: ${data.cost_usd ?? "Unavailable"}`;
        playgroundMessages.appendChild(assistant);
        if (![...playgroundEvaluationSession.options].some(option => option.value === data.session_id)) {
          const option = document.createElement("option");
          option.value = data.session_id;
          option.textContent = `${data.session_id} · Playground provider call`;
          playgroundEvaluationSession.appendChild(option);
        }
        playgroundEvaluationSession.value = data.session_id;
        if (loadSessionEvaluationHistory) loadSessionEvaluationHistory(data.session_id);
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
      toggleMobileNavigation();
    } else {
      sidebar.classList.toggle("collapsed");
      window.localStorage.setItem("agent-replay-sidebar-collapsed", String(sidebar.classList.contains("collapsed")));
    }
  });
  function toggleMobileNavigation() {
    const isOpen = sidebar.classList.toggle("mobile-open");
    sidebarOverlay.hidden = !isOpen;
    mobileNavToggle.setAttribute("aria-expanded", String(isOpen));
    mobileNavToggle.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
  }
  mobileNavToggle.addEventListener("click", toggleMobileNavigation);
  sidebarOverlay.addEventListener("click", () => {
    sidebar.classList.remove("mobile-open");
    sidebarOverlay.hidden = true;
    mobileNavToggle.setAttribute("aria-expanded", "false");
    mobileNavToggle.setAttribute("aria-label", "Open navigation");
  });
  sidebarLinks.forEach(link => link.addEventListener("click", () => switchTab(link.dataset.tab)));

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
      bar.style.width = `${
        point.total_cost_usd != null && maxCost
          ? (point.total_cost_usd / maxCost) * 100
          : 0
      }%`;
      if (point.total_cost_usd == null) bar.style.display = "none";
      track.appendChild(bar);
      const value = document.createElement("span");
      value.textContent = formatCost(point.total_cost_usd, point.cost_status);
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
    fetchReplayValidationHistory(replaySessionSelect.value);
  }

  async function fetchReplayValidationHistory(sessionId) {
    replayValidationHistoryEl.replaceChildren();
    if (!sessionId) {
      replayValidationHistoryEl.textContent = "Select a session to view validation attempts.";
      return;
    }
    try {
      const response = await fetch(
        `/api/sessions/${encodeURIComponent(sessionId)}/replay-validations`
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load replay validation history.");
      if (!data.validations.length) {
        replayValidationHistoryEl.textContent = "No strict replay validations have been recorded.";
        return;
      }
      data.validations.forEach(validation => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "overview-session";
        button.textContent = `${validation.validated_at} · ${validation.status}`;
        button.addEventListener("click", () => renderStrictReplayValidation(validation));
        replayValidationHistoryEl.appendChild(button);
      });
    } catch (err) {
      replayValidationHistoryEl.textContent = `Unable to load replay validation history: ${err.message}`;
    }
  }

  function renderStrictReplayValidation(validation) {
    const output = document.createElement("pre");
    output.className = "code-block";
    output.textContent = JSON.stringify(validation, null, 2);
    replayResultsEl.replaceChildren(output);
  }

  async function runStrictReplayValidation() {
    const sessionId = replaySessionSelect.value;
    if (!sessionId) {
      replayResultsEl.textContent = "Select a session before validating strict replay.";
      return;
    }
    runReplayBtn.disabled = true;
    replayResultsEl.textContent = "Validating the recorded trace; no agent will be executed...";
    try {
      const response = await fetch(
        `/api/sessions/${encodeURIComponent(sessionId)}/replay-validations`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      const validation = await response.json();
      if (!response.ok) throw new Error(validation.detail || "Strict replay validation failed.");
      renderStrictReplayValidation(validation);
      await fetchReplayValidationHistory(sessionId);
    } catch (err) {
      replayResultsEl.textContent = `Strict replay validation failed: ${err.message}`;
    } finally {
      runReplayBtn.disabled = false;
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
    if (!options.substituteSeq && replayModeSelect.value === "strict") {
      await runStrictReplayValidation();
      return;
    }
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
    currentExperimentId = data.experiment_id;
    evaluateExperimentBtn.disabled = false;
    experimentResultsEl.replaceChildren();
    const summary = document.createElement("pre");
    summary.className = "code-block";
    summary.textContent = [
      `Experiment: ${data.experiment_id}`,
      `Parent session: ${data.parent_session_id}`,
      `Fork session: ${data.fork_session_id}`,
      `Substituted event: #${data.substitution.seq} ${JSON.stringify(data.substitution.result)}`,
      "",
      `Baseline (${data.evidence?.baseline || "recorded workflow"}): ${JSON.stringify(data.outcomes.baseline)}`,
      `Strict replay (${data.evidence?.strict_replay || "recorded-result replay"}): ${JSON.stringify(data.outcomes.strict_replay)}`,
      `Forked execution (${data.evidence?.forked || "execution after substitution"}): ${JSON.stringify(data.outcomes.forked)}`,
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
        ? `Cost delta: ${formatCost(data.metrics.cost_usd_estimate.delta, data.metrics.cost_usd_estimate.status)}`
        : "Cost: unavailable; no comparable model cost was recorded.",
      "",
      "Event differences:",
      JSON.stringify(
        { changed: data.events.changed, added: data.events.added, removed: data.events.removed },
        null,
        2
      ),
    ].join("\n");
    experimentResultsEl.appendChild(summary);
    if (loadExperimentEvaluations) loadExperimentEvaluations(data.experiment_id);

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
      const usageButton = document.createElement("button");
      usageButton.type = "button";
      usageButton.className = "btn btn-secondary";
      usageButton.textContent = `Usage for ${sessionId}`;
      usageButton.addEventListener("click", () => {
        switchTab("cost");
        if (![...usageSessionFilter.options].some(option => option.value === sessionId)) {
          const option = document.createElement("option");
          option.value = sessionId;
          option.textContent = sessionId;
          usageSessionFilter.appendChild(option);
        }
        usageSessionFilter.value = sessionId;
        fetchUsage();
      });
      experimentResultsEl.appendChild(usageButton);
    });
  }

  async function fetchExperimentBaselines() {
    experimentBaselineSelect.replaceChildren();
    experimentEventSelect.replaceChildren();
    try {
      const response = await fetch("/api/experiments/baselines");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load eligible baselines.");
      if (!data.baselines.length) {
        const option = document.createElement("option");
        option.textContent = "No supported session available";
        option.value = "";
        experimentBaselineSelect.appendChild(option);
        runExperimentBtn.disabled = true;
        experimentResultsEl.textContent =
          "No eligible baseline found. Guided comparisons currently require a recorded scenario-2 account workflow.";
        return;
      }
      data.baselines.forEach(baseline => {
        const option = document.createElement("option");
        option.value = baseline.session_id;
        option.textContent = `${baseline.session_id} · ${baseline.event_count} events`;
        experimentBaselineSelect.appendChild(option);
      });
      experimentBaselineSelect.dataset.baselines = JSON.stringify(data.baselines);
      if (currentSessionData && data.baselines.some(item => item.session_id === currentSessionData.session_id)) {
        experimentBaselineSelect.value = currentSessionData.session_id;
      }
      updateExperimentEventOptions();
      runExperimentBtn.disabled = false;
    } catch (err) {
      experimentResultsEl.textContent = `Unable to load experiment baselines: ${err.message}`;
      runExperimentBtn.disabled = true;
    }
  }

  function updateExperimentEventOptions() {
    const baselines = JSON.parse(experimentBaselineSelect.dataset.baselines || "[]");
    const baseline = baselines.find(item => item.session_id === experimentBaselineSelect.value);
    experimentEventSelect.replaceChildren();
    (baseline?.substitutable_events || []).forEach(event => {
      const option = document.createElement("option");
      option.value = event.seq;
      option.textContent = `#${event.seq} ${event.type}: ${event.name}`;
      experimentEventSelect.appendChild(option);
    });
  }

  async function fetchExperimentHistory() {
    try {
      const response = await fetch("/api/experiments");
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load saved comparisons.");
      experimentHistoryEl.replaceChildren();
      if (!data.experiments.length) {
        experimentHistoryEl.textContent = "No saved comparisons yet.";
        return;
      }
      data.experiments.forEach(experiment => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "overview-session";
        button.textContent = `${experiment.experiment_id} · ${experiment.baseline_session_id} → ${experiment.fork_session_id}`;
        button.addEventListener("click", () => openSavedExperiment(experiment.experiment_id));
        experimentHistoryEl.appendChild(button);
      });
    } catch (err) {
      experimentHistoryEl.textContent = `Unable to load saved comparisons: ${err.message}`;
    }
  }

  async function openSavedExperiment(experimentId) {
    try {
      const response = await fetch(`/api/experiments/${encodeURIComponent(experimentId)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to load this comparison.");
      renderExperiment(data.result);
    } catch (err) {
      experimentResultsEl.textContent = `Unable to open comparison: ${err.message}`;
    }
  }

  async function runExperiment() {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 30000);
    try {
      runExperimentBtn.disabled = true;
      let substituteResult;
      try {
        substituteResult = JSON.parse(experimentResultInput.value);
      } catch (_) {
        throw new Error("Replacement response must be valid JSON.");
      }
      experimentResultsEl.textContent = "Running strict replay and supported fork execution...";
      const res = await fetch("/api/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          baseline_session_id: experimentBaselineSelect.value,
          substitute_seq: Number(experimentEventSelect.value),
          substitute_result: substituteResult,
        }),
        signal: controller.signal,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Experiment failed");
      renderExperiment(data);
      experimentEvaluationResults.textContent =
        "Comparison created. Evaluate both recorded outputs with the criteria above.";
      await fetchSessions();
      await fetchExperimentHistory();
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
      populateEvaluationSessions(allSessions);
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
      cost.className = `cost-pill ${sess.cost_status === "unavailable" ? "unavailable" : ""}`;
      cost.textContent = formatCost(sess.total_cost_usd, sess.cost_status);
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
      fetchReplayValidationHistory(sessionId);
      if ([...playgroundEvaluationSession.options].some(option => option.value === sessionId)) {
        playgroundEvaluationSession.value = sessionId;
        if (loadSessionEvaluationHistory) loadSessionEvaluationHistory(sessionId);
      }
      sessionContext.textContent = `Session: ${sessionId}`;
      sessionContext.disabled = false;

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
    metricCost.textContent = formatCost(data.total_cost_usd, data.cost_status);
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
      cost.textContent = e.type === "model_call"
        ? formatCost(e.cost_usd, e.cost_status)
        : "—";
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
      const [statusResponse, res] = await Promise.all([
        fetch("/api/live/status"),
        fetch("/api/live/scenarios"),
      ]);
      if (!statusResponse.ok) throw new Error("Unable to load live capability status.");
      const capability = await statusResponse.json();
      liveCapabilityStatus.textContent = capability.message;
      liveExecutionEnabled = capability.execution_enabled;
      runLiveBtn.disabled = !liveExecutionEnabled;
      if (!res.ok) throw new Error("Failed to load live scenarios");
      const scenarios = await res.json();
      liveScenarioSelect.replaceChildren();
      Object.entries(scenarios).forEach(([id, details]) => {
        const option = document.createElement("option");
        option.value = id;
        option.textContent = `${details.label} — ${details.description} (${details.expected_duration})`;
        option.disabled = !capability.execution_enabled;
        liveScenarioSelect.appendChild(option);
      });
      if (!capability.execution_enabled) {
        liveRunStatusEl.textContent = "Scenario execution is disabled by server configuration.";
        liveRunStatusEl.className = "live-run-status hidden";
      }
    } catch (err) {
      liveExecutionEnabled = false;
      runLiveBtn.disabled = true;
      liveCapabilityStatus.textContent = `Unable to load live capability status: ${err.message}`;
      liveScenarioSelect.replaceChildren();
      const errOpt = document.createElement("option");
      errOpt.textContent = `Error loading scenarios: ${err.message}`;
      liveScenarioSelect.appendChild(errOpt);
    }
  }

  async function refreshLiveMonitor() {
    try {
      const response = await fetch("/api/sessions");
      if (!response.ok) throw new Error("Unable to refresh recorded activity.");
      allSessions = await response.json();
      sessionCountBadge.textContent = `${allSessions.length} Sessions`;
      populateReplaySessions(allSessions);
      renderSessionsList(allSessions);
      renderLiveRecentSessions(allSessions.slice(0, 8));
    } catch (err) {
      liveRecentSessions.textContent = `Unable to refresh recorded activity: ${err.message}`;
    }
  }

  function renderLiveRecentSessions(sessions) {
    liveRecentSessions.replaceChildren();
    if (!sessions.length) {
      liveRecentSessions.textContent = "No recorded sessions are available yet.";
      return;
    }
    sessions.forEach(session => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "overview-session";
      button.textContent = `${session.session_id} · ${session.event_count} events · ${
        session.has_errors ? "contains errors" : "no recorded errors"
      }`;
      button.addEventListener("click", async () => {
        await selectSession(session.session_id);
        switchTab("timeline");
      });
      liveRecentSessions.appendChild(button);
    });
  }

  async function runLiveScenario() {
    if (!liveScenarioSelect || !liveScenarioSelect.value || runLiveBtn.disabled) return;
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
        msgSpan.textContent = `Done — ${data.event_count} events; cost ${formatCost(data.total_cost_usd, data.cost_status)}.`;
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
          await refreshLiveMonitor();
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
      runLiveBtn.disabled = !liveExecutionEnabled;
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
  sessionContext.addEventListener("click", () => {
    if (currentSessionData) switchTab("timeline");
  });
  sidebar.classList.toggle(
    "collapsed",
    window.localStorage.getItem("agent-replay-sidebar-collapsed") === "true"
  );
  experimentBaselineSelect.addEventListener("change", updateExperimentEventOptions);
  [usageProviderFilter, usageModelFilter, usageSessionFilter].forEach(filter => {
    filter.addEventListener("change", () => {
      if (document.querySelector('[data-panel="cost"]').classList.contains("active")) {
        fetchUsage();
      }
    });
  });

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
  replaySessionSelect.addEventListener("change", () => {
    fetchReplayValidationHistory(replaySessionSelect.value);
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