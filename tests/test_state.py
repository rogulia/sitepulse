from datetime import datetime, timedelta, timezone

import pytest

import state

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def stored(since_hours_ago, alerted_hours_ago=None):
    alerted = since_hours_ago if alerted_hours_ago is None else alerted_hours_ago
    return {
        "since": (NOW - timedelta(hours=since_hours_ago)).isoformat(),
        "last_alert": (NOW - timedelta(hours=alerted)).isoformat(),
        "message": "old",
    }


def test_new_failure_is_alerted_and_recorded():
    result = state.reconcile({}, {"a": "boom"}, {"a"}, NOW)
    assert result.alerts == {"a": "new"}
    assert result.failing["a"]["since"] == NOW.isoformat()
    assert result.recovered == {}


def test_known_failure_is_silent_until_reminder_interval():
    quiet = state.reconcile({"a": stored(5)}, {"a": "boom"}, {"a"}, NOW)
    assert quiet.alerts == {}
    assert quiet.failing["a"]["since"] == stored(5)["since"]
    assert quiet.failing["a"]["message"] == "boom"

    remind = state.reconcile({"a": stored(30, 25)}, {"a": "boom"}, {"a"}, NOW)
    assert remind.alerts == {"a": "reminder"}
    assert remind.failing["a"]["last_alert"] == NOW.isoformat()
    assert remind.failing["a"]["since"] == stored(30)["since"]


def test_recovery_reports_downtime():
    result = state.reconcile({"a": stored(3)}, {}, {"a"}, NOW)
    assert result.recovered == {"a": timedelta(hours=3)}
    assert result.failing == {}


def test_unprobed_key_is_dropped_without_recovery():
    result = state.reconcile({"gone": stored(3)}, {}, {"other"}, NOW)
    assert result.recovered == {}
    assert result.failing == {}


def test_append_run_trims_history():
    data = {
        "runs": [
            {"ts": (NOW - timedelta(hours=60)).isoformat(), "checked": 1, "failed": 0},
            {"ts": (NOW - timedelta(hours=1)).isoformat(), "checked": 1, "failed": 0},
        ]
    }
    state.append_run(data, NOW, checked=3, failed=1)
    assert [r["checked"] for r in data["runs"]] == [1, 3]


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(minutes=5), "5m"),
        (timedelta(hours=2, minutes=15), "2h 15m"),
        (timedelta(days=3, hours=4), "3d 4h"),
    ],
)
def test_format_duration(delta, expected):
    assert state.format_duration(delta) == expected


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SITEPULSE_STATE_DIR", str(tmp_path / "nested"))
    assert state.load_state("health") == {"failing": {}, "runs": []}
    state.save_state("health", {"failing": {"k": {}}, "runs": []})
    assert state.load_state("health")["failing"] == {"k": {}}
