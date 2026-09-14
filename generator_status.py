"""Cross-process snapshot of the idle/batch generator queue.

The service process writes this file; RunScript dialogs read it because they
do not share the live GeneratorWorker instance.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field

import xbmcvfs

_STATUS_PATH = "special://profile/addon_data/service.trickplay/generator-queue.json"
_MAX_QUEUED_STORED = 40


@dataclass
class GeneratorQueueSnapshot:
    state: str = "idle"
    current_path: str = ""
    queued: list[str] = field(default_factory=list)
    idle_remaining: int = 0
    last_error: str = ""
    paused: bool = False

    @property
    def queued_count(self) -> int:
        return len(self.queued)


def _local_status_path() -> str:
    return xbmcvfs.translatePath(_STATUS_PATH)


def display_name(path: str) -> str:
    """Short label: parent folder + filename."""
    if not path:
        return ""
    cleaned = path.replace("\\", "/").rstrip("/")
    name = os.path.basename(cleaned)
    parent = os.path.basename(os.path.dirname(cleaned))
    if parent:
        return f"{parent} / {name}"
    return name


def format_queue_report(snapshot: GeneratorQueueSnapshot) -> str:
    """Human-readable queue body for a dialog (basenames only)."""
    lines = [f"State: {snapshot.state}"]
    if snapshot.paused:
        lines.append("Paused while video is playing.")
    current = display_name(snapshot.current_path)
    lines.append(f"Current: {current or '(none)'}")
    lines.append(f"Queued: {snapshot.queued_count}")
    if snapshot.idle_remaining:
        lines.append(f"Idle remaining: {snapshot.idle_remaining}")
    if snapshot.last_error:
        lines.append(f"Last error: {snapshot.last_error}")
    if snapshot.queued:
        lines.append("")
        lines.append("Next:")
        for path in snapshot.queued[:20]:
            lines.append(f"- {display_name(path)}")
        extra = snapshot.queued_count - 20
        if extra > 0:
            lines.append(f"…and {extra} more")
    return "\n".join(lines)


def write_queue_snapshot(snapshot: GeneratorQueueSnapshot) -> None:
    path = _local_status_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    payload = asdict(snapshot)
    payload["queued"] = list(snapshot.queued[:_MAX_QUEUED_STORED])
    fd, temporary = tempfile.mkstemp(
        prefix=".generator-queue-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def read_queue_snapshot() -> GeneratorQueueSnapshot:
    path = _local_status_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, TypeError, ValueError):
        return GeneratorQueueSnapshot()
    if not isinstance(data, dict):
        return GeneratorQueueSnapshot()
    queued = data.get("queued") or []
    if not isinstance(queued, list):
        queued = []
    return GeneratorQueueSnapshot(
        state=str(data.get("state") or "idle"),
        current_path=str(data.get("current_path") or ""),
        queued=[str(item) for item in queued if item],
        idle_remaining=int(data.get("idle_remaining") or 0),
        last_error=str(data.get("last_error") or ""),
        paused=bool(data.get("paused")),
    )
