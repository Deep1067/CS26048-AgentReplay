from pathlib import Path

APP_JS = Path(__file__).parents[1] / "src" / "agent_replay" / "ui" / "static" / "app.js"
APP_HTML = APP_JS.with_name("index.html")
APP_CSS = APP_JS.with_name("app.css")


def test_experiment_and_live_buttons_are_wired_after_handler_definitions():
    source = APP_JS.read_text(encoding="utf-8")

    experiment_handler = source.index("async function runExperiment()")
    experiment_listener = source.index('runExperimentBtn.addEventListener("click", runExperiment)')
    live_handler = source.index("async function runLiveScenario()")
    live_listener = source.index('runLiveBtn.addEventListener("click", runLiveScenario)')

    assert experiment_handler < experiment_listener
    assert live_handler < live_listener
    assert 'fetch("/api/experiments"' in source
    assert 'fetch("/api/experiments/baselines"' in source
    assert "fetch(`/api/experiments/${encodeURIComponent(experimentId)}`)" in source
    assert 'fetch("/api/live/run"' in source


def test_mobile_navigation_has_an_accessible_header_toggle():
    html = APP_HTML.read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")

    assert 'id="mobile-nav-toggle"' in html
    assert 'aria-controls="app-sidebar"' in html
    assert ".mobile-nav-toggle { display: inline-flex; }" in css
    assert "@media (max-width: 600px)" in css
    assert "#session-count-badge { display: none; }" in css
    assert 'mobileNavToggle.addEventListener("click", toggleMobileNavigation)' in source
    assert 'mobileNavToggle.setAttribute("aria-expanded", "false")' in source
    assert "sidebar.inert = !isOpen" in source
    assert 'event.key === "Escape"' in source
    assert 'link.setAttribute("aria-current", "page")' in source


def test_visual_system_respects_focus_and_reduced_motion():
    css = APP_CSS.read_text(encoding="utf-8")

    assert ":focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "var(--focus-ring)" in css
    assert "@media (max-width: 600px)" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css


def test_session_picker_is_keyboard_accessible():
    source = APP_JS.read_text(encoding="utf-8")

    assert 'const item = document.createElement("button")' in source
    assert 'item.type = "button"' in source
    assert 'item.setAttribute("aria-current", "true")' in source
    assert "selectSession(sess.session_id, event.detail === 0)" in source
    assert (
        "sessionsListEl.querySelector('.session-item[aria-current=\"true\"]')?.focus();" in source
    )


def test_external_fonts_do_not_block_initial_script_loading():
    html = APP_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")

    assert 'id="google-fonts"' in html
    assert 'rel="stylesheet" media="print"' in html
    assert 'document.getElementById("google-fonts")' in source
    assert 'googleFonts.media = "all"' in source


def test_privileged_tokens_are_transient_and_use_separate_headers():
    html = APP_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")

    assert 'id="live-auth-token"' in html
    assert 'id="pricing-auth-token"' in html
    assert 'id="detector-auth-token"' in html
    assert 'headers["X-Live-Run-Token"]' in source
    assert 'headers["X-Config-Mutations-Token"]' in source
    assert "localStorage.setItem('live-auth-token'" not in source
    assert "localStorage.setItem('pricing-auth-token'" not in source
    assert "localStorage.setItem('detector-auth-token'" not in source


def test_timeline_distinguishes_empty_sessions_from_filtered_results():
    source = APP_JS.read_text(encoding="utf-8")

    assert "events.length" in source
    assert '"No events recorded in this session."' in source
    assert '"No events match the current filters."' in source


def test_experiment_and_playground_have_recorded_output_evaluation_controls():
    html = APP_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")

    assert 'id="experiment-evaluation-criteria"' in html
    assert 'id="evaluate-experiment-btn"' in html
    assert 'id="experiment-evaluation-history"' in html
    assert 'id="playground-evaluation-session"' in html
    assert 'id="evaluate-recorded-session-btn"' in html
    assert 'id="playground-evaluation-history"' in html
    assert "/api/experiments/${encodeURIComponent(currentExperimentId)}/evaluations" in source
    assert "/api/evaluations/sessions/${encodeURIComponent(sessionId)}" in source
    assert "output_source" in source


def test_replay_history_and_versioned_suite_selectors_are_connected():
    html = APP_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")

    assert 'id="replay-validation-history"' in html
    assert "/api/sessions/${encodeURIComponent(sessionId)}/replay-validations" in source
    assert 'fetch("/api/evaluation-suites")' in source
    assert "/api/evaluation-suites/${encodeURIComponent(suite.suite_id)}/versions" in source
    assert "suite_id: suite.suite_id, suite_version: suite.version" in source
    assert "record.suite_id" in source
    assert "No strict replay validations have been recorded." in source
    assert "loadExperimentEvaluations = fetchExperimentEvaluations" in source
    assert "loadExperimentEvaluations(data.experiment_id)" in source
    assert "loadSessionEvaluationHistory(sessionId)" in source
    assert "not comparable:" in source


def test_session_selection_defers_hidden_history_and_reuses_loaded_trace():
    source = APP_JS.read_text(encoding="utf-8")
    replay_sessions = source.split("function populateReplaySessions(sessions) {", 1)[1].split(
        "async function fetchReplayValidationHistory", 1
    )[0]
    replay_guide_sessions = source.split("function populateReplayGuide(sessions) {", 1)[1].split(
        "function renderReplayGuideValidation", 1
    )[0]
    selection = source.split("async function selectSession(", 1)[1].split(
        "function renderSessionMetrics", 1
    )[0]

    assert 'if (tabPanelsActive("replay"))' in replay_sessions
    assert 'if (tabPanelsActive("replay-guide")) refreshReplayGuide(currentSessionData)' in (
        replay_guide_sessions
    )
    assert 'if (tabPanelsActive("replay")) {' in selection
    assert 'if (tabPanelsActive("replay-guide")) refreshReplayGuide(currentSessionData)' in (
        selection
    )
    assert "async function refreshReplayGuide(loadedSession = null)" in source
    assert "const sessionRequest = loadedSession?.session_id === sessionId" in source


def test_live_model_run_form_polls_persisted_runs_and_links_to_sessions():
    html = APP_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")

    assert 'id="live-provider-select"' in html
    assert 'id="live-model-select"' in html
    assert 'id="live-task-prompt"' in html
    assert 'id="live-auth-token"' in html
    assert 'id="live-run-history"' in html
    assert 'fetch("/api/live/runs"' in source
    assert "async function launchLiveModelRun()" in source
    assert "fetch(`/api/live/runs/${encodeURIComponent(created.run_id)}`)" in source
    assert 'launchLiveModelBtn.addEventListener("click", launchLiveModelRun)' in source


def test_replay_guide_actions_use_existing_trace_replay_and_experiment_workflows():
    html = APP_HTML.read_text(encoding="utf-8")
    source = APP_JS.read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")

    for element_id in (
        "replay-guide-session",
        "replay-guide-session-status",
        "replay-guide-open-trace",
        "replay-guide-validate",
        "replay-guide-validation-history",
        "replay-guide-event",
        "replay-guide-recorded-value",
        "replay-guide-substitute",
        "replay-guide-run-fork",
        "replay-guide-evaluate-session",
        "replay-guide-open-experiments",
        "replay-guide-open-replay",
    ):
        assert f'id="{element_id}"' in html
    assert 'data-tab="replay-guide"' in html
    assert 'data-panel="replay-guide"' in html
    assert 'new Set(["overview", "timeline", "replay-guide"' in source
    assert "populateReplayGuide(allSessions)" in source
    assert 'fetch("/api/experiments/baselines")' in source
    assert "/api/sessions/${encodeURIComponent(sessionId)}/replay-validations" in source
    assert "selectSession(replayGuideSessionSelect.value)" in source
    assert 'switchTab("timeline")' in source
    assert 'switchTab("replay")' in source
    assert 'switchTab("experiment")' in source
    assert 'switchTab("playground")' in source
    assert "const result = await runExperiment();" in source
    assert "await experimentBaselinesLoad" in source
    assert 'replayGuideRunFork.addEventListener("click", runReplayGuideFork)' in source
    assert ".replay-guide" in css
    assert ".guide-actions { display: flex; flex-wrap: wrap;" in css
