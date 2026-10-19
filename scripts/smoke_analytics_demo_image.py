"""Offline hosting-image smoke: no mounts, env files, host scripts or provider calls.

Build first: docker build -f deploy/Dockerfile -t veyra-demo-autoload:test .
Run: python scripts/smoke_analytics_demo_image.py
Only containers with a fresh run-specific name are removed; no volumes are created.
"""

import argparse
import json
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4


def run_smoke(image):
    name = "veyra-demo-smoke-" + uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="veyra-image-smoke-") as empty_directory:

        def docker(*args):
            return subprocess.check_output(
                ["docker", *args], cwd=empty_directory, text=True, timeout=120
            ).strip()

        def start():
            docker(
                "run", "--detach", "--name", name, "--publish", "127.0.0.1::8000", image
            )
            address = docker("port", name, "8000/tcp")
            return "http://" + address

        def get(base, path):
            with urlopen(base + path, timeout=10) as response:
                return json.load(response)

        def wait_ready(base):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    if get(base, "/health")["status"] == "ok":
                        return
                except (URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(0.5)
            raise RuntimeError("Hosting image did not become healthy within 60 seconds")

        def verify(base):
            health = get(base, "/health")
            assert health["analytics_demo"]["enabled"]
            overview = get(base, "/api/analytics/overview?source=synthetic_demo")
            assert overview["total_sessions"] == 144
            assert overview["retained_events"] == 688
            assert overview["latency"]["agent_ms"] == {"average_ms": None, "samples": 0}
            assert get(base, "/api/analytics/events?source=runtime")["total"] == 0
            assert (
                get(base, "/api/analytics/sessions?source=synthetic_demo&active=true")[
                    "total"
                ]
                == 0
            )
            assert get(base, "/api/analytics/anomalies?source=synthetic_demo")[
                "anomalies"
            ]
            assert get(base, "/api/analytics/sessions/synthetic-demo-v1-002/journey")[
                "stages"
            ]
            identities = []
            for offset in (0, 500):
                page = get(base, f"/api/analytics/events?limit=500&offset={offset}")
                assert page["total"] == 688
                identities.extend(e["event_id"] for e in page["events"])
            assert len(set(identities)) == 688
            with urlopen(base + "/", timeout=10) as response:
                assert b'<div id="root">' in response.read()
            # Execute only an inspection, not a seed, in the installed Python package.
            docker(
                "exec",
                name,
                "python",
                "-c",
                "import os; from pathlib import Path; from importlib.resources import files; "
                "assert os.getuid() != 0; "
                "assert not Path('/app/scripts').exists(); "
                "assert not Path('/app/.env').exists(); "
                "assert not Path('/app/backend/.env').exists(); "
                "assert files('app.analytics').joinpath('fixtures/demo-v1.json').is_file(); "
                "assert os.access('/app/data/runtime/veyra_events.db', os.W_OK)",
            )
            return set(identities)

        try:
            base = start()
            wait_ready(base)
            identities = verify(base)
            print(
                "Fresh image: 144 sessions / 688 events; APIs, static UI and package verified",
                flush=True,
            )
            docker("restart", name)
            base = "http://" + docker("port", name, "8000/tcp")
            wait_ready(base)
            assert verify(base) == identities
            print("Same-container restart: stable IDs, no duplicates", flush=True)
            docker("rm", "--force", name)
            base = start()
            wait_ready(base)
            assert verify(base) == identities
            print(
                "Container recreation without mounts: dataset restored automatically",
                flush=True,
            )
        finally:
            subprocess.run(
                ["docker", "rm", "--force", name],
                cwd=empty_directory,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="veyra-demo-autoload:test")
    run_smoke(parser.parse_args().image)
