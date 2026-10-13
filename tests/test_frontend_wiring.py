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
