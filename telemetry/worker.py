"""Headless pollers; archive latest observations without depending on a UI."""
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time

from backend.pihole import Config, DnsSource, forward
from backend.unifi import Inventory


def save(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as out:
        try:
            json.dump(value, out, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
            os.replace(out.name, path)
        finally:
            if os.path.exists(out.name):
                os.unlink(out.name)


def records(source, snapshot):
    stamp = snapshot["observed_at"]
    base = {"_time": stamp, "hostname": "unifi-controller" if source == "unifi" else "ns0",
            "app_name": source + "-snapshot", "schema": "1", "observed_at": stamp}
    entities = [("snapshot", "site", {"snapshot_json": json.dumps(snapshot, separators=(",", ":"))})]
    if source == "unifi":
        base.update(site_id=snapshot["site"]["id"], partial=str(snapshot["partial"]).lower())
        for group in ("devices", "clients", "networks"):
            entities.extend((group[:-1], row["id"], row) for row in snapshot[group])
    result = []
    for kind, identity, fields in entities:
        row = {**base, "entity_kind": kind, "entity_id": identity}
        for key, value in fields.items():
            if value is not None:
                row[key] = json.dumps(value, separators=(",", ":")) if isinstance(value, (list, dict)) else value
        row["event_id"] = hashlib.sha256(f"{source}:{stamp}:{kind}:{identity}".encode()).hexdigest()
        row["_msg"] = f"{source} {kind} {fields.get('name') or identity} observation"
        result.append(row)
    return result


class SnapshotArchive:
    """One durable pending batch per source; retries are byte-identical.

    This is sampled inventory, not a change audit. During archive outages the
    pending sample is retained, then the newest sample is sent after recovery.
    Intermediate samples can be skipped; source timestamps disclose the gaps.
    """
    def __init__(self, path, source, config, sender=forward):
        self.path, self.source, self.config, self.sender = Path(path), source, config, sender
        self.state = {"version": 1, "through": None, "pending": None}
        self.error = None
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if self.state.get("version") != 1 or not all(k in self.state for k in ("through", "pending")):
                raise ValueError("Invalid snapshot checkpoint; refusing to replace it")

    def poll(self, snapshot):
        try:
            pending = self.state["pending"]
            if pending is None and snapshot and snapshot["observed_at"] != self.state["through"]:
                pending = {"through": snapshot["observed_at"], "rows": records(self.source, snapshot)}
                state = {**self.state, "pending": pending}
                save(self.path, state)
                self.state = state
            if pending:
                self.sender(self.config, pending["rows"], time.monotonic() + 6)
                state = {"version": 1, "through": pending["through"], "pending": None}
                save(self.path, state)
                self.state = state
            self.error = None
        except Exception:
            self.error = "Snapshot archive failed; pending checkpoint retained for retry."

    def status(self):
        return {"through": self.state["through"], "pending": bool(self.state["pending"]), "error": self.error}


def main():
    root = Path(os.environ.get("TELEMETRY_STATE_DIR", "/analysis"))
    inventory = Inventory(root / "unifi-inventory.json")
    dns = DnsSource(root / "pihole-state.json")
    config = Config.from_env()
    archives = {name: SnapshotArchive(root / (name + "-archive.json"), name, config)
                for name in ("unifi", "pihole")}
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    inventory.start_worker()
    dns.start_worker()
    try:
        while not stop.is_set():
            sources = {"unifi": inventory.status(), "pihole": dns.status()}
            for name, status in sources.items():
                # Never relabel a stale cache as a new observation.
                archives[name].poll(status.get("snapshot") if not status["stale"] else None)
                status.pop("snapshot", None)
            save(root / "telemetry-status.json", {"updated_at": time.time(), "sources": sources,
                 "snapshot_archives": {name: archive.status() for name, archive in archives.items()}})
            stop.wait(5)
    finally:
        # Signal both before joining, keeping shutdown within Compose grace time.
        inventory.stop.set()
        dns.stop.set()
        inventory.stop_worker()
        dns.stop_worker()


if __name__ == "__main__":
    main()
