"""Report Bedrock invocations recorded by a deployed server (proves the instance role path)."""
import json
import sys

import requests

base = sys.argv[1]
st = requests.get(base + "/api/system/status", timeout=10).json()
inv = requests.get(base + "/api/ai/invocations", timeout=10).json()
print(json.dumps({"bedrock": st["bedrock"], "s3": st["s3"]}, indent=1))
for i in inv:
    print(i["invocation_id"], i["kind"], i["status"], i["live"], i["model_id"], i.get("latency_ms"), i.get("input_tokens"), i.get("failure_reason"))
