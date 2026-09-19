"""Run only inside a disposable Daytona Linux sandbox.

Download one official, pinned Node Linux release, verify it against the
release's SHA-256 manifest, and extract just the node binary.
"""

import hashlib
from pathlib import Path
import shutil
import sys
import tarfile
from urllib.request import urlopen


version = sys.argv[1]
if version not in {"26.7.0", "26.8.1", "26.9.0"}:
    raise SystemExit("unsupported version")
base = f"https://nodejs.org/dist/v{version}/"
filename = f"node-v{version}-linux-x64.tar.xz"
with urlopen(base + "SHASUMS256.txt", timeout=30) as response:
    manifest = response.read().decode("ascii")
expected = next(line.split()[0] for line in manifest.splitlines()
                if line.split()[-1] == filename)
archive = Path("/tmp") / filename
with urlopen(base + filename, timeout=90) as response, archive.open("wb") as target:
    shutil.copyfileobj(response, target)
actual = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
if actual != expected:
    raise SystemExit("SHA-256 mismatch")
with tarfile.open(archive, "r:xz") as bundle:
    member = f"node-v{version}-linux-x64/bin/node"
    with bundle.extractfile(member) as source, Path("/tmp/node-fixture").open("wb") as target:
        shutil.copyfileobj(source, target)
Path("/tmp/node-fixture").chmod(0o755)
print("node_sha256_verified", version, actual)
