"""Public build identity and the schema required by this release."""
import os
import re

EXPECTED_REVISION = "0021"


def identity():
    sha = os.getenv("KRUVIM_RELEASE_SHA") or os.getenv("VERCEL_GIT_COMMIT_SHA", "")
    return {"commit": sha if re.fullmatch(r"[0-9a-f]{40}", sha) else "local",
            "required_database_revision": EXPECTED_REVISION}


def worker_health_key(kind):
    return f"kruvim:{kind}:{identity()['commit']}:{os.getenv('HOSTNAME', 'local')}:health"


def worker_health_pattern(kind):
    return f"kruvim:{kind}:{identity()['commit']}:*:health"
