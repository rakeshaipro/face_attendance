"""CLI utilities.

  python -m app.cli gen-encryption-key
  python -m app.cli create-api-key --label "Admin" --scope admin
  python -m app.cli list-api-keys
  python -m app.cli revoke-api-key <id>
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone

from cryptography.fernet import Fernet

from app.core.enums import Scope
from app.core.security import generate_api_key, hash_api_key
from app.db import SessionLocal
from app.models import ApiKey


def cmd_gen_encryption_key(_: argparse.Namespace) -> int:
    print(Fernet.generate_key().decode("ascii"))
    print("# Copy this to FA_ENCRYPTION_KEY in your .env", file=sys.stderr)
    return 0


def cmd_create_api_key(args: argparse.Namespace) -> int:
    plaintext = generate_api_key()
    with SessionLocal() as db:
        key = ApiKey(
            id=uuid.uuid4().hex,
            label=args.label,
            key_hash=hash_api_key(plaintext),
            key_prefix=plaintext[:8],
            scope=Scope(args.scope).value,
            is_active=True,
        )
        if args.expires_days:
            from datetime import timedelta

            key.expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_days)
        db.add(key)
        db.commit()
        kid = key.id
    print(f"API key created (id={kid}).")
    print("Plaintext (shown once):")
    print(plaintext)
    return 0


def cmd_list_api_keys(_: argparse.Namespace) -> int:
    from sqlalchemy import select

    with SessionLocal() as db:
        rows = db.execute(select(ApiKey).order_by(ApiKey.created_at.desc())).scalars().all()
    if not rows:
        print("No API keys.")
        return 0
    print(f"{'id':<34} {'prefix':<10} {'scope':<10} {'active':<7} label")
    for k in rows:
        print(f"{k.id:<34} {k.key_prefix:<10} {k.scope:<10} {str(k.is_active):<7} {k.label}")
    return 0


def cmd_revoke_api_key(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    with SessionLocal() as db:
        row = db.execute(select(ApiKey).where(ApiKey.id == args.key_id)).scalar_one_or_none()
        if row is None:
            print(f"No API key with id={args.key_id}", file=sys.stderr)
            return 1
        row.is_active = False
        db.commit()
    print(f"Revoked API key {args.key_id}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="face-attendance", description="Face Attendance CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-api-key", help="Create a new API key.")
    c.add_argument("--label", required=True)
    c.add_argument("--scope", choices=[s.value for s in Scope], default=Scope.READONLY.value)
    c.add_argument("--expires-days", type=int, default=None)
    c.set_defaults(func=cmd_create_api_key)

    sub.add_parser("list-api-keys", help="List API keys (no plaintext).")

    r = sub.add_parser("revoke-api-key", help="Revoke an API key by id.")
    r.add_argument("key_id")
    r.set_defaults(func=cmd_revoke_api_key)

    g = sub.add_parser("gen-encryption-key", help="Generate a Fernet key for camera-cred encryption.")
    g.set_defaults(func=cmd_gen_encryption_key)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
