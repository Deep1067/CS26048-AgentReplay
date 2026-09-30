from agent_replay.interceptors.model_interceptor import record_model_call
from agent_replay.pricing import PriceEngine
from agent_replay.recorder import record_session
from agent_replay.session_service import SessionService
from agent_replay.storage import SQLiteStorage


def test_pricing_calculation():
    engine = PriceEngine()
    # gemini-1.5-flash: in=0.075/M, out=0.30/M
    # 10,000 in = 0.00075, 2,000 out = 0.0006 -> 0.00135
    cost = engine.calculate_cost("gemini-1.5-flash", tokens_in=10000, tokens_out=2000)
    assert abs(cost - 0.00135) < 1e-6


def test_pricing_prefix_and_alias_matching():
    engine = PriceEngine()
    cost1 = engine.calculate_cost("models/gemini-1.5-flash-001", tokens_in=1_000_000, tokens_out=0)
    assert abs(cost1 - 0.075) < 1e-6

    cost2 = engine.calculate_cost("gemini-2.0-flash-exp", tokens_in=1_000_000, tokens_out=0)
    assert abs(cost2 - 0.10) < 1e-6


def test_pricing_unknown_model_fallback():
    engine = PriceEngine()
    # Default is 0.10 in / 0.40 out
    cost = engine.calculate_cost(
        "custom-finetuned-llama", tokens_in=1_000_000, tokens_out=1_000_000
    )
    assert abs(cost - 0.50) < 1e-6


def test_pricing_missing_file_fallback(tmp_path):
    engine = PriceEngine(prices_path=tmp_path / "nonexistent.json")
    cost = engine.calculate_cost("any-model", tokens_in=1_000_000, tokens_out=0)
    assert abs(cost - 0.10) < 1e-6


def test_session_totals_and_cost_aggregation():
    storage = SQLiteStorage(db_path=":memory:")
    service = SessionService(storage=storage)

    class MockUsage:
        prompt_token_count = 50_000
        candidates_token_count = 10_000

    class MockResponse:
        usage_metadata = MockUsage()
        text = "Hello world"

    def mock_llm():
        return MockResponse()

    with record_session("sess_totals", storage=storage):
        record_model_call("gemini-1.5-flash", mock_llm)
        record_model_call("gemini-1.5-flash", mock_llm)

    details = service.get_session_details("sess_totals")
    assert details is not None
    assert details["session_id"] == "sess_totals"
    assert details["event_count"] == 2
    assert details["model_calls_count"] == 2
    assert details["tool_calls_count"] == 0
    assert details["total_tokens_in"] == 100_000
    assert details["total_tokens_out"] == 20_000

    # Each call: 50k*0.075/1M + 10k*0.30/1M = 0.00375 + 0.003 = 0.00675
    # Two calls: 0.0135
    assert abs(details["total_cost_usd"] - 0.0135) < 1e-5
