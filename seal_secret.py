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


DATA_FILE_MESSAGE = "Stop. The bot's data file can't be read. Please check it."


def _key_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seal.key")


def _tighten_key(path):
    """Mode 0600 when the file is looser. A failure leaves the bytes alone."""
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        return
    if mode & ~0o600:
        try:
            os.chmod(path, 0o600)
        except OSError:
            return


def _read_installed(path):
    """The stored key, or None. A short or unreadable file is left untouched."""
    try:
        with open(path, "rb") as handle:
            current = handle.read()
    except OSError:
        return None
    if len(current) >= 32:
        return current
    return None


def install_secret():
    """32 random bytes for this install. The same file is reused after the first run.

    The file is created as mode 0600. If it already exists and cannot be read,
    this returns None and does not overwrite it.
    """
    path = _key_path()
    if os.path.exists(path):
        secret = _read_installed(path)
        if secret is None:
            return None
        _tighten_key(path)
        return secret
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_installed(path)
    except OSError:
        return None
    try:
        os.write(descriptor, os.urandom(32))
        os.fsync(descriptor)
    except OSError:
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    try:
        os.chmod(path, 0o600)
    except OSError:
        return None
    return _read_installed(path)


def seal_hex(domain, payload):
    """Hex HMAC for one domain. domain is a short label such as b'readiness'."""
    secret = install_secret()
    if not secret:
        raise OSError(DATA_FILE_MESSAGE)
    if isinstance(domain, str):
        domain = domain.encode("utf-8")
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hmac.new(secret, domain + b"\0" + payload, hashlib.sha256).hexdigest()
