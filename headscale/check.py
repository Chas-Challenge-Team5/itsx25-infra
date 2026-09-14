"""Run Linux checks using the pinned binary, without installing a package/service."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

from setup import download_package

with tempfile.TemporaryDirectory(prefix="headscale-check-") as directory:
    root = Path(directory)
    package = root / "headscale.deb"
    download_package(package)
    subprocess.run(["dpkg-deb", "--extract", str(package), str(root / "package")], check=True)
    environment = os.environ | {"HEADSCALE_TEST_BINARY": str(root / "package/usr/bin/headscale")}
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "headscale/tests", "-v"],
        cwd=Path(__file__).resolve().parents[1], env=environment, check=True,
    )
