#!/usr/bin/env python3
"""Download one DB-IP Lite release. Preserve versions; switch the active link atomically.

Downloads only a public database. Never sends observed IP addresses to DB-IP.
Run manually when updating; no scheduler is installed by this script.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request


def digest(path, algorithm):
    result = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--month", default=datetime.now(timezone.utc).strftime("%Y-%m"))
    parser.add_argument("--sha1", required=True, help="Release checksum from DB-IP's official download page")
    args = parser.parse_args()
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", args.month) or not re.fullmatch(r"[a-fA-F0-9]{40}", args.sha1):
        parser.error("Invalid release month or SHA1 checksum")
    args.directory.mkdir(parents=True, exist_ok=True)
    release = args.directory / f"dbip-city-lite-{args.month}.mmdb"
    active = args.directory / "dbip-city-lite.mmdb"
    url = f"https://download.db-ip.com/free/dbip-city-lite-{args.month}.mmdb.gz"
    with tempfile.TemporaryDirectory(prefix=".geoip-download-", dir=args.directory) as work:
        archive, unpacked = Path(work) / "release.gz", Path(work) / "release.mmdb"
        request = urllib.request.Request(url, headers={"User-Agent": "Visibility-homelab/0.1"})
        with urllib.request.urlopen(request, timeout=60) as source, archive.open("wb") as destination:
            size = 0
            while block := source.read(1024 * 1024):
                size += len(block)
                if size > 256 * 1024 * 1024:
                    raise RuntimeError("Compressed database exceeds size limit")
                destination.write(block)
        with gzip.open(archive, "rb") as source, unpacked.open("wb") as destination:
            size = 0
            while block := source.read(1024 * 1024):
                size += len(block)
                if size > 512 * 1024 * 1024:
                    raise RuntimeError("Uncompressed database exceeds size limit")
                destination.write(block)
        sha1 = args.sha1.lower()
        if sha1 not in (digest(archive, "sha1"), digest(unpacked, "sha1")):
            raise RuntimeError("Release checksum mismatch; active database unchanged")
        with unpacked.open("rb") as handle:
            handle.seek(max(0, size - 128 * 1024))
            if b"\xab\xcd\xefMaxMind.com" not in handle.read():
                raise RuntimeError("MMDB metadata marker missing")
        sha256 = digest(unpacked, "sha256")
        if release.exists():
            if digest(release, "sha256") != sha256:
                raise RuntimeError("A different file already exists for this release; refusing to replace it")
        else:
            os.chmod(unpacked, 0o644)
            os.replace(unpacked, release)
        temporary_link = Path(work) / "active.mmdb"
        temporary_link.symlink_to(release.name)
        # The link's relative target is interpreted after it moves into the data directory.
        os.replace(temporary_link, active)
        metadata = {"provider": "DB-IP Lite", "release": args.month, "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    "source": url, "sha256": sha256, "bytes": size, "license": "CC BY 4.0"}
        metadata_path = Path(work) / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        os.replace(metadata_path, args.directory / "metadata.json")
        print(json.dumps({"release": args.month, "bytes": size, "sha256": sha256, "status": "ready"}))


if __name__ == "__main__":
    main()
