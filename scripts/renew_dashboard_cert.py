#!/usr/bin/env python3
"""Inspect or renew the AI-02 presentation console leaf certificate.

Signs a fresh 90-day leaf certificate for CN=ai-02-visibility with the existing
local CA (telemetry-api/server.crt + server.key), preserving SANs, key usage,
and EKU. Never prints private key material. Validates the new certificate with
strict OpenSSL server/IP checks before atomically swapping it into place.

Usage:
  python3 scripts/renew_dashboard_cert.py --check
  python3 scripts/renew_dashboard_cert.py --apply
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

DEFAULT_CA_CERT = Path("/home/klab/.local/share/visibility/presentation/dashboard-ca.crt")
DEFAULT_CERT_DIR = Path("/home/klab/.local/share/visibility/presentation")
DEFAULT_SAN = "DNS:ai-02,DNS:localhost,IP:192.168.5.230,IP:127.0.0.1"
DEFAULT_VERIFY_IP = "192.168.5.230"
DEFAULT_DAYS = 90


def run_openssl(args):
    result = subprocess.run(
        ["openssl", *args], capture_output=True, text=True, timeout=20
    )
    if result.returncode != 0:
        raise RuntimeError(f"openssl {args[0]} failed (exit {result.returncode})")
    return result.stdout


def cert_info(cert_path: Path) -> dict:
    out = run_openssl(["x509", "-in", str(cert_path), "-noout", "-subject", "-issuer", "-enddate", "-fingerprint", "-sha256"])
    info = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        info[key.strip().lower()] = val.strip()
    not_after = datetime.strptime(info["notafter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    days = round((not_after - datetime.now(timezone.utc)).total_seconds() / 86400, 2)
    return {
        "path": str(cert_path),
        "subject": info.get("subject", ""),
        "issuer": info.get("issuer", ""),
        "not_after": not_after.isoformat().replace("+00:00", "Z"),
        "days_remaining": days,
        "sha256": info.get("sha256 fingerprint", ""),
    }


def renew_cert(
    ca_cert: Path,
    ca_key: Path,
    cert_dir: Path,
    *,
    days: int = DEFAULT_DAYS,
    san: str = DEFAULT_SAN,
    verify_ip: str = DEFAULT_VERIFY_IP,
    cn: str = "ai-02-visibility",
    apply: bool = False,
) -> dict:
    if not 7 <= days <= 397:
        raise ValueError("days must be between 7 and 397")
    if not ca_cert.is_file() or not ca_key.is_file():
        raise FileNotFoundError("CA certificate or key file is missing")
    cert_dir.mkdir(parents=True, exist_ok=True)
    target_cert = cert_dir / "dashboard.crt"
    target_key = cert_dir / "dashboard.key"

    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix=".cert-renew-", dir=cert_dir) as work:
        work_dir = Path(work)
        new_key = work_dir / "dashboard.key"
        csr = work_dir / "dashboard.csr"
        new_cert = work_dir / "dashboard.crt"
        ext = work_dir / "ext.cnf"
        serial = work_dir / "ca.srl"

        ext.write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            f"subjectAltName={san}\n",
            encoding="utf-8",
        )

        run_openssl(["genrsa", "-out", str(new_key), "2048"])
        os.chmod(new_key, 0o600)
        run_openssl(["req", "-new", "-key", str(new_key), "-subj", f"/CN={cn}", "-out", str(csr)])
        run_openssl([
            "x509", "-req",
            "-in", str(csr),
            "-CA", str(ca_cert),
            "-CAkey", str(ca_key),
            "-CAcreateserial",
            "-CAserial", str(serial),
            "-out", str(new_cert),
            "-days", str(days),
            "-sha256",
            "-extfile", str(ext),
        ])
        os.chmod(new_cert, 0o644)

        verify_args = ["verify", "-x509_strict", "-purpose", "sslserver", "-CAfile", str(ca_cert)]
        if verify_ip:
            verify_args.extend(["-verify_ip", verify_ip])
        verify_args.append(str(new_cert))
        run_openssl(verify_args)

        details = cert_info(new_cert)
        if not apply:
            return {"status": "dry-run-ok", "candidate": details}

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backups = []
        for existing in (target_cert, target_key):
            if existing.exists():
                backup = existing.with_name(f"{existing.name}.bak-{stamp}")
                shutil.copy2(existing, backup)
                os.chmod(backup, 0o600 if existing == target_key else 0o644)
                backups.append(str(backup))

        os.replace(new_key, target_key)
        os.replace(new_cert, target_cert)
        os.chmod(target_key, 0o600)
        os.chmod(target_cert, 0o644)
        return {
            "status": "renewed",
            "cert": cert_info(target_cert),
            "backups": backups,
            "next_step": "Recreate console: docker compose -f /home/klab/.local/share/visibility/presentation-deploy/compose.live.yaml up -d --no-deps --pull never --force-recreate console",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Inspect current dashboard.crt expiry")
    mode.add_argument("--dry-run", action="store_true", help="Generate and verify a candidate cert without replacing files")
    mode.add_argument("--apply", action="store_true", help="Renew and atomically replace dashboard.crt and dashboard.key")
    parser.add_argument("--ca-cert", type=Path, default=DEFAULT_CA_CERT)
    parser.add_argument("--ca-key", type=Path, default=None, help="Issuing CA private key (required for --dry-run/--apply)")
    parser.add_argument("--cert-dir", type=Path, default=DEFAULT_CERT_DIR)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--san", default=DEFAULT_SAN)
    parser.add_argument("--verify-ip", default=DEFAULT_VERIFY_IP)
    args = parser.parse_args()

    if args.check:
        cert = args.cert_dir / "dashboard.crt"
        info = cert_info(cert)
        verify_args = ["verify", "-x509_strict", "-purpose", "sslserver", "-CAfile", str(args.ca_cert)]
        if args.verify_ip:
            verify_args.extend(["-verify_ip", args.verify_ip])
        verify_args.append(str(cert))
        run_openssl(verify_args)
        info["chain_verified"] = True
        print(json.dumps(info, indent=2))
        return
    if args.ca_key is None:
        parser.error("--ca-key is required for --dry-run and --apply")
    result = renew_cert(
        args.ca_cert,
        args.ca_key,
        args.cert_dir,
        days=args.days,
        san=args.san,
        verify_ip=args.verify_ip,
        apply=args.apply,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
