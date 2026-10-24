"""Task 1 gate: prove real AWS + Bedrock multimodal access before building anything else.

Usage:
    python scripts/verify_bedrock.py                 # synthetic test image
    python scripts/verify_bedrock.py --image <path>  # real image (e.g. NOAA crop)

Exits non-zero naming the failing step. Writes the selected model to data/aws_config.json.
Credentials come only from the environment (never from files in the repo).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-1"

# Preference order: strongest vision models first. Inference profile ids are tried
# first because newer models only support cross-region profiles.
PREFERENCE = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-lite-v1:0",
    "amazon.nova-pro-v1:0",
    "amazon.nova-lite-v1:0",
]

TOOL = {
    "toolSpec": {
        "name": "report_image",
        "description": "Report what is visible in the image.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "contains_road": {"type": "boolean"},
                    "contains_water": {"type": "boolean"},
                },
                "required": ["description", "contains_road", "contains_water"],
            }
        },
    }
}


def fail(step: str, err: Exception | str) -> None:
    print(f"[FAIL] {step}: {err}")
    sys.exit(1)


def synthetic_image() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (512, 512), (70, 110, 60))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 220, 512, 300], fill=(60, 90, 140))  # river
    d.rectangle([230, 0, 280, 512], fill=(90, 90, 90))  # road
    d.line([255, 0, 255, 512], fill=(230, 230, 80), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--model")
    args = ap.parse_args()

    session = boto3.Session(region_name=REGION)
    try:
        ident = session.client("sts").get_caller_identity()
        print(f"[OK] STS identity account={ident['Account']} arn={ident['Arn']}")
    except Exception as e:  # noqa: BLE001
        fail("sts:GetCallerIdentity", e)

    bedrock = session.client("bedrock")
    available: set[str] = set()
    try:
        fms = [m for m in bedrock.list_foundation_models()["modelSummaries"]
               if "IMAGE" in m.get("inputModalities", [])]
        available |= {m["modelId"] for m in fms}
        print(f"[OK] {len(fms)} image-capable foundation models listed")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] list_foundation_models: {e}")
    try:
        profs = bedrock.list_inference_profiles(maxResults=1000)["inferenceProfileSummaries"]
        available |= {p["inferenceProfileId"] for p in profs}
        print(f"[OK] {len(profs)} inference profiles listed")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] list_inference_profiles: {e}")

    candidates = [args.model] if args.model else [m for m in PREFERENCE if m in available] or PREFERENCE
    image = Path(args.image).read_bytes() if args.image else synthetic_image()
    fmt = (Path(args.image).suffix.lstrip(".").lower() if args.image else "png").replace("jpg", "jpeg")

    rt = session.client("bedrock-runtime", config=Config(read_timeout=60, retries={"max_attempts": 2}))
    errors = {}
    for model in candidates:
        t0 = time.perf_counter()
        try:
            resp = rt.converse(
                modelId=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"image": {"format": fmt, "source": {"bytes": image}}},
                        {"text": "Describe this aerial image briefly using the report_image tool. Do not invent details."},
                    ],
                }],
                toolConfig={"tools": [TOOL], "toolChoice": {"tool": {"name": "report_image"}}},
                inferenceConfig={"maxTokens": 400, "temperature": 0},
            )
        except Exception as e:  # noqa: BLE001
            errors[model] = str(e)[:200]
            print(f"[SKIP] {model}: {str(e)[:160]}")
            continue
        latency = (time.perf_counter() - t0) * 1000
        tool_use = next((c["toolUse"] for c in resp["output"]["message"]["content"] if "toolUse" in c), None)
        print(f"[OK] Bedrock converse model={model} latency_ms={latency:.0f} usage={resp.get('usage')}")
        print("[OK] parsed tool output:", json.dumps(tool_use["input"] if tool_use else None, indent=2))
        cfg_path = ROOT / "data" / "aws_config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        cfg.update({"region": REGION, "account": ident["Account"], "bedrock_model_id": model,
                    "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "verify_latency_ms": round(latency)})
        cfg_path.write_text(json.dumps(cfg, indent=2))
        print(f"[OK] wrote {cfg_path.relative_to(ROOT)}")
        return
    fail("bedrock-runtime:Converse (all candidates)", json.dumps(errors, indent=2))


if __name__ == "__main__":
    main()
