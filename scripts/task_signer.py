#!/usr/bin/env python3
"""
Task signer / verifier for Symphony Task Runner.

Usage:
    python3 task_signer.py keygen --name <signer-name>
        -> writes private key to ~/.config/symphony/<name>.ed25519.priv (mode 600)
        -> appends pubkey line to ops/work_queue/AUTHORIZED_KEYS.txt

    python3 task_signer.py sign --task <path-to-json> --priv <priv-key-path>
        -> computes signature, writes back into the JSON file's "signature" field

    python3 task_signer.py verify --task <path-to-json>
        -> loads AUTHORIZED_KEYS.txt, tries each pubkey, prints "OK <signer-name>" or exits non-zero

Signature scheme:
    - Ed25519 over a canonical JSON serialization of the task with the
      "signature" field removed.
    - Canonical JSON: sort_keys=True, no whitespace separators, UTF-8.
    - Private keys: raw Ed25519 32-byte seed, base64-encoded, stored in
      ~/.config/symphony/<name>.ed25519.priv (mode 600).
    - Public keys in ops/work_queue/AUTHORIZED_KEYS.txt: one line per key in
      the form `<signer-name> <base64-pubkey>`. Lines starting with `#` are
      comments (used for placeholders). Blank lines are ignored.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


REPO_ROOT = Path(__file__).resolve().parent.parent
AUTHORIZED_KEYS_PATH = REPO_ROOT / "ops" / "work_queue" / "AUTHORIZED_KEYS.txt"
PRIV_KEY_DIR = Path.home() / ".config" / "symphony"


def canonical_bytes(task: dict) -> bytes:
    """Return canonical UTF-8 JSON bytes for signing.

    The "signature" field is removed before serialization so the signature
    covers only the task body. Keys are sorted; no whitespace is emitted.
    """
    body = {k: v for k, v in task.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def load_authorized_keys() -> list[tuple[str, Ed25519PublicKey]]:
    """Load `(name, pubkey)` pairs from AUTHORIZED_KEYS.txt.

    Lines starting with `#` or blank lines are ignored. Malformed lines are
    skipped with a warning to stderr so a bad entry never stops verification
    of other keys.
    """
    keys: list[tuple[str, Ed25519PublicKey]] = []
    if not AUTHORIZED_KEYS_PATH.exists():
        return keys
    for lineno, raw in enumerate(AUTHORIZED_KEYS_PATH.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            print(
                f"warn: AUTHORIZED_KEYS.txt line {lineno} malformed (skipping): {line!r}",
                file=sys.stderr,
            )
            continue
        name, pub_b64 = parts
        try:
            pub_bytes = base64.b64decode(pub_b64)
            pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
        except Exception as exc:  # noqa: BLE001
            print(
                f"warn: AUTHORIZED_KEYS.txt line {lineno} bad pubkey ({exc}); skipping",
                file=sys.stderr,
            )
            continue
        keys.append((name, pub))
    return keys


def cmd_keygen(args: argparse.Namespace) -> int:
    """Generate a keypair; write priv to disk, append pub to AUTHORIZED_KEYS.

    The private key is written to ~/.config/symphony/<name>.ed25519.priv with
    mode 600. The public key is appended as a line `<name> <base64>` to
    ops/work_queue/AUTHORIZED_KEYS.txt.
    """
    name: str = args.name
    if not name or any(c.isspace() for c in name):
        print("error: --name must be a single non-empty token", file=sys.stderr)
        return 2

    PRIV_KEY_DIR.mkdir(parents=True, exist_ok=True)
    priv_path = PRIV_KEY_DIR / f"{name}.ed25519.priv"
    if priv_path.exists() and not args.force:
        print(
            f"error: {priv_path} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 2

    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    # Write private key (base64 of 32-byte seed) with mode 600.
    priv_b64 = base64.b64encode(raw_priv).decode("ascii")
    # os.open with 0o600 creates the file with tight perms atomically.
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (priv_b64 + "\n").encode("ascii"))
    finally:
        os.close(fd)

    # Append pubkey line to AUTHORIZED_KEYS.txt, creating file if needed.
    pub_b64 = base64.b64encode(raw_pub).decode("ascii")
    AUTHORIZED_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = AUTHORIZED_KEYS_PATH.read_text() if AUTHORIZED_KEYS_PATH.exists() else ""
    new_line = f"{name} {pub_b64}\n"
    if new_line.strip() in (line.strip() for line in existing.splitlines()):
        # Pubkey already present; avoid duplicate line.
        pass
    else:
        with AUTHORIZED_KEYS_PATH.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(new_line)

    print(f"wrote private key: {priv_path} (mode 600)")
    print(f"appended pubkey line to: {AUTHORIZED_KEYS_PATH}")
    print(f"pubkey: {pub_b64}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    """Sign a task JSON in place; the signature goes into task['signature']."""
    task_path = Path(args.task)
    priv_path = Path(args.priv).expanduser()
    if not task_path.exists():
        print(f"error: task not found: {task_path}", file=sys.stderr)
        return 2
    if not priv_path.exists():
        print(f"error: private key not found: {priv_path}", file=sys.stderr)
        return 2

    priv_b64 = priv_path.read_text().strip()
    try:
        priv_raw = base64.b64decode(priv_b64)
        priv = Ed25519PrivateKey.from_private_bytes(priv_raw)
    except Exception as exc:  # noqa: BLE001
        print(f"error: bad private key ({exc})", file=sys.stderr)
        return 2

    task = json.loads(task_path.read_text())
    if not isinstance(task, dict):
        print("error: task JSON must be an object", file=sys.stderr)
        return 2

    sig = priv.sign(canonical_bytes(task))
    task["signature"] = base64.b64encode(sig).decode("ascii")

    # Pretty-print with sorted keys so diffs are stable.
    task_path.write_text(
        json.dumps(task, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"signed: {task_path}")
    return 0


def verify_task(task: dict) -> tuple[bool, str]:
    """Return (ok, signer_name_or_reason) for a task dict.

    Tries every pubkey in AUTHORIZED_KEYS.txt until one verifies. If no key
    matches, returns (False, reason).
    """
    sig_b64 = task.get("signature")
    if not sig_b64:
        return False, "no signature field"
    try:
        sig = base64.b64decode(sig_b64)
    except Exception as exc:  # noqa: BLE001
        return False, f"bad signature b64: {exc}"

    body = canonical_bytes(task)
    keys = load_authorized_keys()
    if not keys:
        return False, "no authorized keys configured"

    for name, pub in keys:
        try:
            pub.verify(sig, body)
            return True, name
        except InvalidSignature:
            continue
        except Exception as exc:  # noqa: BLE001
            # Malformed key or other verify error; keep trying.
            print(f"warn: verify error for {name}: {exc}", file=sys.stderr)
            continue
    return False, "signature did not match any authorized key"


def cmd_verify(args: argparse.Namespace) -> int:
    task_path = Path(args.task)
    if not task_path.exists():
        print(f"error: task not found: {task_path}", file=sys.stderr)
        return 2
    task = json.loads(task_path.read_text())
    ok, detail = verify_task(task)
    if ok:
        print(f"OK {detail}")
        return 0
    print(f"FAIL {detail}", file=sys.stderr)
    return 1


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Symphony task signer/verifier")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_keygen = sub.add_parser("keygen", help="generate keypair + enroll pubkey")
    p_keygen.add_argument("--name", required=True, help="signer name (single token)")
    p_keygen.add_argument("--force", action="store_true", help="overwrite existing private key")
    p_keygen.set_defaults(func=cmd_keygen)

    p_sign = sub.add_parser("sign", help="sign a task JSON in place")
    p_sign.add_argument("--task", required=True, help="path to task JSON")
    p_sign.add_argument("--priv", required=True, help="path to private key file")
    p_sign.set_defaults(func=cmd_sign)

    p_verify = sub.add_parser("verify", help="verify a task JSON against AUTHORIZED_KEYS")
    p_verify.add_argument("--task", required=True, help="path to task JSON")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
