import json

import pytest

from agent_replay.detector.config import DetectorConfig
from agent_replay.detector.rules import (
    HighCostSessionRule,
    LongDurationSessionRule,
    RepeatedToolCallsRule,
)
from agent_replay.models import Event
from agent_replay.session_service import SessionService
from agent_replay.storage import SQLiteStorage


@pytest.fixture
def storage():
    return SQLiteStorage(db_path=":memory:")


def test_repeated_tool_calls_rule(storage):
    rule = RepeatedToolCallsRule()
    config = DetectorConfig(max_repeated_tool_calls=3)

    # 3 identical consecutive calls to search_docs
    events = [
        Event(
            session_id="s1",
            seq=1,
            type="tool_call",
            name="search_docs",
            args_json=json.dumps({"q": "docs"}),
        ),
        Event(
            session_id="s1",
            seq=2,
            type="tool_call",
            name="search_docs",
            args_json=json.dumps({"q": "docs"}),
        ),
        Event(
            session_id="s1",
            seq=3,
            type="tool_call",
            name="search_docs",
            args_json=json.dumps({"q": "docs"}),
        ),
    ]

    flags = rule.evaluate("s1", events, storage, config)
    assert len(flags) == 1
    assert flags[0].rule_name == "repeated_tool_calls"
    assert flags[0].severity == "danger"
    assert flags[0].culprit_seqs == [1, 2, 3]


def test_repeated_tool_calls_not_triggered_when_different_args(storage):
    rule = RepeatedToolCallsRule()
    config = DetectorConfig(max_repeated_tool_calls=3)

    events = [
        Event(
            session_id="s2",
            seq=1,
            type="tool_call",
            name="search_docs",
            args_json=json.dumps({"q": "a"}),
        ),
        Event(
            session_id="s2",
            seq=2,
            type="tool_call",
            name="search_docs",
            args_json=json.dumps({"q": "b"}),
        ),
        Event(
            session_id="s2",
            seq=3,
            type="tool_call",
            name="search_docs",
            args_json=json.dumps({"q": "c"}),
        ),
    ]

    flags = rule.evaluate("s2", events, storage, config)
    assert len(flags) == 0


def test_repeated_tool_calls_deduplicates_each_pattern(storage):
    rule = RepeatedToolCallsRule()
    config = DetectorConfig(max_repeated_tool_calls=3)
    events = [
        Event(
            session_id="s3",
            seq=seq,
            type="tool_call",
            name="search_docs",
            args_json=json.dumps({"q": "docs"}),
        )
        for seq in range(1, 6)
    ]

    flags = rule.evaluate("s3", events, storage, config)

    assert len(flags) == 1
    assert flags[0].culprit_seqs == [1, 2, 3, 4, 5]


def test_high_cost_session_rule(storage):
    rule = HighCostSessionRule()
    config = DetectorConfig(cost_multiplier_over_median=3.0, min_sessions_for_cost_median=3)

    # Seed 3 historical sessions with ~$0.01 cost
    for i in range(1, 4):
        sid = f"hist_{i}"
        storage.create_session(sid)
        storage.save_event(
            Event(session_id=sid, seq=1, type="model_call", name="m", args_json="{}", cost_usd=0.01)
        )

    # Anomaly session with $0.10 cost (10x median)
    anomaly_events = [
        Event(
            session_id="spike_sess",
            seq=1,
            type="model_call",
            name="m",
            args_json="{}",
            cost_usd=0.10,
        )
    ]

    flags = rule.evaluate("spike_sess", anomaly_events, storage, config)
    assert len(flags) == 1
    assert flags[0].rule_name == "high_cost_session"
    assert flags[0].severity == "warning"
    assert "higher than the historical median" in flags[0].message


def test_long_duration_and_runaway_events_rule(storage):
    rule = LongDurationSessionRule()
    config = DetectorConfig(max_duration_ms=5000.0, max_events_per_session=5)

    events = [
        Event(
            session_id="long_sess",
            seq=i,
            type="tool_call",
            name=f"t_{i}",
            args_json="{}",
            duration_ms=1000.0,
        )
        for i in range(1, 8)
    ]  # 7 events, 7000ms duration

    flags = rule.evaluate("long_sess", events, storage, config)
    assert len(flags) == 2
    rule_names = [f.rule_name for f in flags]
    assert "long_duration_session" in rule_names
    assert "runaway_events" in rule_names


def test_session_service_surfaces_flags(storage):
    service = SessionService(storage=storage)
    storage.create_session("sess_with_loop")

    for i in range(1, 4):
        storage.save_event(
            Event(
                session_id="sess_with_loop",
                seq=i,
                type="tool_call",
                name="db_query",
                args_json=json.dumps({"sql": "SELECT 1"}),
            )
        )

    details = service.get_session_details("sess_with_loop")
    assert details is not None
    assert len(details["flags"]) >= 1
    assert details["flags"][0]["rule_name"] == "repeated_tool_calls"
