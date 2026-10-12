from pathlib import Path

APP_JS = Path(__file__).parents[1] / "src" / "agent_replay" / "ui" / "static" / "app.js"


def test_experiment_and_live_buttons_are_wired_after_handler_definitions():
    source = APP_JS.read_text(encoding="utf-8")

    experiment_handler = source.index("async function runExperiment()")
    experiment_listener = source.index('runExperimentBtn.addEventListener("click", runExperiment)')
    live_handler = source.index("async function runLiveScenario()")
    live_listener = source.index('runLiveBtn.addEventListener("click", runLiveScenario)')

    assert experiment_handler < experiment_listener
    assert live_handler < live_listener
    assert 'fetch("/api/experiments/counterfactual"' in source
    assert 'fetch("/api/live/run"' in source
