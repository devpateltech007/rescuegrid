"""Kill any process listening on the given TCP port (Windows dev helper)."""
import re
import subprocess
import sys

port = sys.argv[1] if len(sys.argv) > 1 else "8000"
out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
pids = {l.split()[-1] for l in out.splitlines() if re.search(rf"[:.]{port}\s+\S+\s+LISTENING", l)}
for pid in pids:
    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
print("killed", sorted(pids))
