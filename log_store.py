#!/usr/bin/env python3
"""
One on-disk JSON log per user.

The file holds meals, sets, check-ins, weights, confirmations, the
used-record list, and sessions. A missing file is created on the first
append. A missing path, an unknown kind, a bad entry, or a corrupt file
fails closed and does not invent rows.
"""

from datetime import date, datetime
import json
import os


KINDS = (
    "meals",
    "sets",
    "checkins",
    "weights",
    "confirmations",
    "used_records",
    "sessions",
)


def _blank():
    return {kind: [] for kind in KINDS}


def _confirmation_ids(raw):
    if not raw:
        return set()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    found = set()
    for row in data.get("confirmations") or []:
        if isinstance(row, dict) and isinstance(row.get("record_id"), str):
            found.add(row["record_id"])
    return found


def _week_landed(folder, new_ids):
    """True when a week file in this folder already holds one of the new ids."""
    if not new_ids or not folder or not os.path.isdir(folder):
        return False
    for name in os.listdir(folder):
        if not name.endswith(".json") or name == "log.json":
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        confirmation = data.get("confirmation")
        if isinstance(confirmation, dict) and confirmation.get("record_id") in new_ids:
            return True
    return False


def _replace_bytes(path, raw):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _log_bytes_valid(raw):
    """True when these bytes are a log this store can keep."""
    if not raw:
        return False
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return False
    if not isinstance(data, dict):
        return False
    for key, value in data.items():
        if key not in KINDS or not isinstance(value, list):
            return False
        if any(not isinstance(item, dict) for item in value):
            return False
    return True


def reconcile_log_backup(log_path):
    """Recover a crashed log only after the recovered bytes validate.

    A plain read never removes log.json.bak. The backup is removed only
    after those bytes have been validated and written over the live log.
    """
    if not isinstance(log_path, str) or not log_path:
        return
    backup_path = log_path + ".bak"
    if not os.path.exists(backup_path):
        return
    try:
        with open(backup_path, "rb") as handle:
            backup_bytes = handle.read()
        live_bytes = b""
        if os.path.exists(log_path):
            with open(log_path, "rb") as handle:
                live_bytes = handle.read()
    except OSError:
        return
    new_ids = _confirmation_ids(live_bytes) - _confirmation_ids(backup_bytes)
    landed = _week_landed(os.path.dirname(log_path), new_ids)
    try:
        if landed or backup_bytes == live_bytes:
            return
        if not _backup_can_replace(backup_bytes, live_bytes):
            return
        if not _log_bytes_valid(backup_bytes):
            return
        _replace_bytes(log_path, backup_bytes)
        with open(log_path, "rb") as handle:
            written = handle.read()
        if written == backup_bytes and _log_bytes_valid(written) and os.path.exists(backup_path):
            os.remove(backup_path)
    except OSError:
        return


_LOG_ROW_TYPES = ("sets", "weights", "meals", "checkins", "confirmations")


def _row_list(data, key):
    if not isinstance(data, dict):
        return []
    value = data.get(key)
    return list(value) if isinstance(value, list) else []


def _row_counts(rows):
    counts = {}
    for item in rows:
        try:
            token = json.dumps(item, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            token = repr(item)
        counts[token] = counts.get(token, 0) + 1
    return counts


def _counts_cover(backup_rows, live_rows):
    live_counts = _row_counts(live_rows)
    backup_counts = _row_counts(backup_rows)
    for token, count in live_counts.items():
        if backup_counts.get(token, 0) < count:
            return False
    return True


def _backup_can_replace(backup_bytes, live_bytes):
    """Replace only when the backup is a strict superset of every record type.

    sets, weights, meals, check-ins, and confirmations each have to cover the
    live rows, and the backup has to hold at least one extra row. An empty or
    unparseable backup never replaces the live log. A missing or unparseable
    live log is treated as empty, so a parseable backup can restore it.
    """
    if not backup_bytes:
        return False
    try:
        backup = json.loads(backup_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return False
    if not isinstance(backup, dict):
        return False
    live = {}
    if live_bytes:
        try:
            parsed = json.loads(live_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            parsed = None
        if isinstance(parsed, dict):
            live = parsed
    backup_total = 0
    live_total = 0
    for key in _LOG_ROW_TYPES:
        backup_rows = _row_list(backup, key)
        live_rows = _row_list(live, key)
        if not _counts_cover(backup_rows, live_rows):
            return False
        backup_total += len(backup_rows)
        live_total += len(live_rows)
    return backup_total > live_total


def _trusted_change(row, changes):
    """History only when this row is a record that covers the stored proposal."""
    proposal = row.get("proposal")
    if not isinstance(proposal, dict):
        return None
    record_id = row.get("record_id")
    plan_hash = row.get("plan_hash")
    quoted = row.get("quoted_words")
    speaker = row.get("speaker")
    if not all(isinstance(value, str) and value for value in (record_id, plan_hash, quoted, speaker)):
        return None
    from record_confirmation import ConfirmationRecord, ConfirmationRecorder

    stamp = row.get("timestamp") if isinstance(row.get("timestamp"), str) else ""
    if not stamp and isinstance(row.get("date"), str):
        stamp = row["date"]
    record = ConfirmationRecord(
        confirmed=True,
        plan_hash=plan_hash,
        quoted_words=quoted,
        speaker=speaker,
        message=row.get("message") if isinstance(row.get("message"), str) else "",
        errors=row.get("errors") if isinstance(row.get("errors"), list) else [],
        record_id=record_id,
        timestamp=stamp,
        issuer_seal=row.get("issuer_seal") if isinstance(row.get("issuer_seal"), str) else "",
    )
    if not ConfirmationRecorder().covers(record, proposal):
        return None
    proposal_changes = proposal.get("changes")
    if not isinstance(proposal_changes, dict):
        return None
    trusted = {}
    for key in ("load", "calories"):
        if key not in changes:
            continue
        if changes[key] != proposal_changes.get(key):
            return None
        trusted[key] = changes[key]
    if not trusted:
        return None
    return {"date": row.get("date"), "confirmed": True, "changes": trusted}


def _ready(value, depth=0):
    """JSON values only. Dates become strings. Anything else is refused."""
    if depth > 8:
        return None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        stored = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return None
            child = _ready(item, depth + 1)
            if child is None and item is not None:
                return None
            stored[key] = child
        return stored
    if isinstance(value, (list, tuple)):
        stored = []
        for item in value:
            child = _ready(item, depth + 1)
            if child is None and item is not None:
                return None
            stored.append(child)
        return stored
    return None


class LogStore:
    """Reads and appends one user's log."""

    def __init__(self, path):
        self.path = None
        self.error = None
        self.data = _blank()
        if path is None or (isinstance(path, str) and not path.strip()):
            self.error = "A log path is required."
            return
        self.path = os.fspath(path)
        loaded = self._read()
        if isinstance(loaded, str):
            self.error = loaded
            self.data = _blank()
        else:
            self.data = loaded

    def append(self, kind, entry):
        if self.error:
            return self._no(self.error)
        if kind not in KINDS:
            return self._no("Unknown log kind.")
        if not isinstance(entry, dict):
            return self._no("The log entry has to be an object.")
        stored = _ready(entry)
        if not isinstance(stored, dict):
            return self._no("The log entry could not be stored.")
        self.data[kind].append(stored)
        try:
            self._write()
        except OSError:
            self.data[kind].pop()
            return self._no("The log could not be saved.")
        return {"ok": True, "stored": True, "message": "Saved.", "entry": stored}

    def drop_last(self, kind):
        """Remove the last row of one kind. Used when a later save fails."""
        if self.error:
            return self._no(self.error)
        if kind not in KINDS or not self.data[kind]:
            return self._no("Nothing to remove.")
        removed = self.data[kind].pop()
        try:
            self._write()
        except OSError:
            self.data[kind].append(removed)
            return self._no("The log could not be saved.")
        return {"ok": True, "stored": True, "message": "Removed."}

    def as_dashboard(self):
        """Rows dashboard.py already knows how to read."""
        if self.error:
            return None
        return {
            "intake": [
                {
                    "date": row.get("date"),
                    "calories": row.get("calories"),
                    "protein_g": row.get("protein_g"),
                }
                for row in self.data["meals"]
            ],
            "weights": [
                {"date": row.get("date"), "kg": row.get("kg", row.get("weight"))}
                for row in self.data["weights"]
            ],
            "sets": [
                {
                    "date": row.get("date"),
                    "exercise": row.get("exercise"),
                    "weight": row.get("weight"),
                    "reps": row.get("reps"),
                }
                for row in self.data["sets"]
            ],
            "sessions": [dict(row) for row in self.data["sessions"]],
        }

    def as_trend(self):
        """Rows trend_review.py already knows how to read.

        Meal confirmations are not load or calorie history. A raw confirmed
        dict does not count. Only a record that covers the stored proposal
        is history. A confirmation that is not a real object still fails the read.
        """
        if self.error:
            return None
        history = []
        for row in self.data["confirmations"]:
            if not isinstance(row, dict):
                return None
            if "changes" not in row:
                continue
            changes = row.get("changes")
            if row.get("confirmed") is not True or not isinstance(changes, dict) or not changes:
                return None
            if any(key not in ("load", "calories") for key in changes):
                return None
            trusted = _trusted_change(row, changes)
            if trusted is None:
                continue
            history.append(trusted)
        training = []
        for row in self.data["checkins"] + self.data["sessions"]:
            if isinstance(row, dict) and "load" in row:
                training.append({"date": row.get("date"), "load": row.get("load")})
        logs = {
            "weights": [
                {"date": row.get("date"), "kg": row.get("kg", row.get("weight"))}
                for row in self.data["weights"]
            ],
            "intake": [
                {
                    "date": row.get("date"),
                    "calories": row.get("calories"),
                    "protein_g": row.get("protein_g"),
                }
                for row in self.data["meals"]
            ],
            "training": training,
            "sessions": [dict(row) for row in self.data["sessions"]],
        }
        if history:
            logs["confirmed_changes"] = history
        return logs

    def _read(self):
        reconcile_log_backup(self.path)
        if not os.path.exists(self.path):
            return _blank()
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return "The log could not be read."
        if not isinstance(data, dict):
            return "The log could not be read."
        cleaned = _blank()
        for key, value in data.items():
            if key not in KINDS or not isinstance(value, list):
                return "The log could not be read."
            if any(not isinstance(item, dict) for item in value):
                return "The log could not be read."
            cleaned[key] = value
        return cleaned

    def _write(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle)
            handle.write("\n")
        os.replace(temporary, self.path)

    def _no(self, message):
        return {"ok": False, "stored": False, "message": message}
