import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from config import BASE_DIR

REMIND_AFTER = timedelta(hours=24)
HISTORY_KEEP = timedelta(hours=48)


def state_dir() -> Path:
    return Path(os.environ.get("SITEPULSE_STATE_DIR") or BASE_DIR / "state")


def load_state(name: str) -> dict:
    path = state_dir() / f"{name}.json"
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"failing": {}, "runs": []}
    data.setdefault("failing", {})
    data.setdefault("runs", [])
    return data


def save_state(name: str, data: dict) -> None:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    temp = path.with_suffix(".tmp")
    with open(temp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(temp, path)


@dataclass
class Transitions:
    failing: dict = field(default_factory=dict)
    alerts: dict = field(default_factory=dict)  # key -> "new" | "reminder"
    recovered: dict = field(default_factory=dict)  # key -> downtime


def reconcile(
    previous: dict,
    current: dict[str, str],
    checked: set[str],
    now: datetime,
    remind_after: timedelta = REMIND_AFTER,
) -> Transitions:
    """Compare failures of this run with the stored ones.

    `previous` maps key -> {"since", "last_alert", "message"} (ISO timestamps);
    `current` maps key -> failure message; `checked` holds every key probed in this
    run. A stored failure whose key was not probed any more is dropped silently.
    """
    result = Transitions()
    for key, message in current.items():
        stored = previous.get(key)
        if stored is None:
            result.failing[key] = {
                "since": now.isoformat(),
                "last_alert": now.isoformat(),
                "message": message,
            }
            result.alerts[key] = "new"
            continue

        last_alert = datetime.fromisoformat(stored["last_alert"])
        entry = {**stored, "message": message}
        if now - last_alert >= remind_after:
            entry["last_alert"] = now.isoformat()
            result.alerts[key] = "reminder"
        result.failing[key] = entry

    for key, stored in previous.items():
        if key in current:
            continue
        if key in checked:
            result.recovered[key] = now - datetime.fromisoformat(stored["since"])
    return result


def append_run(data: dict, now: datetime, checked: int, failed: int) -> None:
    cutoff = now - HISTORY_KEEP
    runs = [r for r in data["runs"] if datetime.fromisoformat(r["ts"]) >= cutoff]
    runs.append({"ts": now.isoformat(), "checked": checked, "failed": failed})
    data["runs"] = runs


def format_duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    days, rest = divmod(minutes, 1440)
    hours, minutes = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
