"""Pre-push check: list tracked files that look like secrets and tracked files larger than 50 MB."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True).stdout.split("\0")
files = [f for f in files if f]
pat = re.compile(rb"(ASIA|AKIA)[A-Z0-9]{16}|aws_secret_access_key\s*=\s*\S{20,}|AWS_SESSION_TOKEN\s*=\s*\S{40,}|ghp_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY")
total, big, hits = 0, [], []
for f in files:
    p = ROOT / f
    if not p.is_file():
        continue
    size = p.stat().st_size
    total += size
    if size > 50e6:
        big.append((f, size))
    if size < 20e6 and pat.search(p.read_bytes()):
        hits.append(f)
    if f.startswith(".secrets") or f.endswith(".env") or "aws.cmd" in f:
        hits.append(f)
print(f"tracked files: {len(files)}, total {total / 1e6:.1f} MB")
print("files > 50 MB:", big or "none")
print("secret matches:", hits or "none")
