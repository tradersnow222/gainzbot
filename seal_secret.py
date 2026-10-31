#!/usr/bin/env python3
"""Per-install HMAC key for result seals.

The key is created at random the first time it is needed and stored in
data/seal.key, which is gitignored. A seal shows that this install issued
the result. It is tamper-evidence, not security: anyone with the file can
recompute a seal.
"""

import hashlib
import hmac
import os


def _key_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seal.key")


def install_secret():
    """32 random bytes for this install. The same file is reused after the first run."""
    path = _key_path()
    try:
        with open(path, "rb") as handle:
            current = handle.read()
        if len(current) >= 32:
            return current
    except OSError:
        current = b""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fresh = os.urandom(32)
    temporary = path + ".tmp"
    try:
        with open(temporary, "wb") as handle:
            handle.write(fresh)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        if os.path.exists(path):
            with open(path, "rb") as handle:
                current = handle.read()
            if len(current) >= 32:
                return current
        return fresh
    with open(path, "rb") as handle:
        stored = handle.read()
    return stored if len(stored) >= 32 else fresh


def seal_hex(domain, payload):
    """Hex HMAC for one domain. domain is a short label such as b'readiness'."""
    if isinstance(domain, str):
        domain = domain.encode("utf-8")
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hmac.new(install_secret(), domain + b"\0" + payload, hashlib.sha256).hexdigest()
