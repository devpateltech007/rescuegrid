"""Show judges that RESCUEGRID 3D really runs on AWS.

  python scripts/deploy/aws_showcase.py setup     # enable Bedrock invocation logging + CloudWatch dashboard
  python scripts/deploy/aws_showcase.py report    # print live evidence from every service + console links
  python scripts/deploy/aws_showcase.py teardown  # remove the dashboard, restore the previous logging config

`report` writes the same text to docs/aws_showcase_report.md. Nothing here touches the running app.
Credentials come from the default boto3 chain (run scripts\\aws_showcase.cmd to load .secrets\\aws.cmd).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import boto3
import requests
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
cfg = json.loads((ROOT / "data" / "aws_config.json").read_text())
dep_path = ROOT / "data" / "deployment.json"
dep = json.loads(dep_path.read_text()) if dep_path.exists() else {}

REGION, ACCOUNT, BUCKET, MODEL = cfg["region"], cfg["account"], cfg["bucket"], cfg["bedrock_model_id"]
NAME = "rescuegrid3d"
APP_LOG_GROUP = f"/{NAME}/app"
INV_LOG_GROUP = f"/{NAME}/bedrock-invocations"
INV_ROLE = f"{NAME}-bedrock-logging"
DASHBOARD = NAME
URL = dep.get("url", "http://32.195.112.28")
INSTANCE = dep.get("instance_id")
PREV_CFG = ROOT / "data" / "runtime" / "bedrock_logging_prev.json"
CONSOLE = f"https://{REGION}.console.aws.amazon.com"

s = boto3.Session(region_name=REGION)
iam, logs, cw, bedrock, ec2, s3c, sts = (s.client(x) for x in ("iam", "logs", "cloudwatch", "bedrock", "ec2", "s3", "sts"))


# ------------------------------------------------------------------ setup
def ensure_log_group(name: str, days: int = 7) -> None:
    try:
        logs.create_log_group(logGroupName=name)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.put_retention_policy(logGroupName=name, retentionInDays=days)


def ensure_logging_role() -> str:
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "bedrock.amazonaws.com"}, "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT},
                      "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock:{REGION}:{ACCOUNT}:*"}}}]}
    try:
        arn = iam.create_role(RoleName=INV_ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                              Description="Bedrock model invocation logging for RESCUEGRID 3D",
                              Tags=[{"Key": "project", "Value": NAME}])["Role"]["Arn"]
        fresh = True
    except iam.exceptions.EntityAlreadyExistsException:
        arn = iam.get_role(RoleName=INV_ROLE)["Role"]["Arn"]
        fresh = False
    policy = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
        "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:{INV_LOG_GROUP}:log-stream:*"}]}
    iam.put_role_policy(RoleName=INV_ROLE, PolicyName="write-invocation-logs", PolicyDocument=json.dumps(policy))
    if fresh:
        time.sleep(10)  # IAM propagation before Bedrock validates the role
    return arn


def enable_invocation_logging(role_arn: str) -> None:
    current = bedrock.get_model_invocation_logging_configuration().get("loggingConfig")
    if current and current.get("cloudWatchConfig", {}).get("logGroupName") != INV_LOG_GROUP and not PREV_CFG.exists():
        PREV_CFG.parent.mkdir(parents=True, exist_ok=True)
        PREV_CFG.write_text(json.dumps(current, indent=1))
        print(f"  saved the account's previous logging config to {PREV_CFG.relative_to(ROOT)}")
    conf = {"cloudWatchConfig": {"logGroupName": INV_LOG_GROUP, "roleArn": role_arn},
            "textDataDeliveryEnabled": True, "imageDataDeliveryEnabled": False,
            "embeddingDataDeliveryEnabled": False}
    for attempt in range(6):
        try:
            bedrock.put_model_invocation_logging_configuration(loggingConfig=conf)
            return
        except ClientError as e:
            if e.response["Error"]["Code"] != "ValidationException" or attempt == 5:
                raise
            time.sleep(10)  # role not yet assumable


def bedrock_model_dims() -> list[str]:
    """ModelId dimension values CloudWatch has seen for our model (profile id and/or base id)."""
    tail = MODEL.split(".", 1)[1] if MODEL.startswith("us.") else MODEL
    seen = set()
    for page in cw.get_paginator("list_metrics").paginate(Namespace="AWS/Bedrock", MetricName="Invocations"):
        for m in page["Metrics"]:
            for d in m["Dimensions"]:
                if d["Name"] == "ModelId" and tail in d["Value"]:
                    seen.add(d["Value"])
    return sorted(seen) or [MODEL]


def put_dashboard() -> None:
    dims = bedrock_model_dims()

    def metric_widget(title, metric, stat, x, y, w=8):
        return {"type": "metric", "x": x, "y": y, "width": w, "height": 6, "properties": {
            "title": title, "region": REGION, "view": "timeSeries", "stat": stat, "period": 60,
            "metrics": [["AWS/Bedrock", metric, "ModelId", d] for d in dims]}}

    body = {"widgets": [
        {"type": "text", "x": 0, "y": 0, "width": 24, "height": 2, "properties": {"markdown":
            f"## RESCUEGRID 3D on AWS\nApp: [{URL}]({URL}) · EC2 `{INSTANCE}` · model `{MODEL}` · "
            f"evidence bucket `{BUCKET}` · region `{REGION}`"}},
        metric_widget("Bedrock invocations / min", "Invocations", "Sum", 0, 2),
        metric_widget("Bedrock latency (ms, avg)", "InvocationLatency", "Average", 8, 2),
        {"type": "metric", "x": 16, "y": 2, "width": 8, "height": 6, "properties": {
            "title": "Bedrock tokens / min", "region": REGION, "view": "timeSeries", "stat": "Sum", "period": 60,
            "metrics": [["AWS/Bedrock", m, "ModelId", d] for d in dims for m in ("InputTokenCount", "OutputTokenCount")]}},
        metric_widget("Bedrock client / server errors", "InvocationClientErrors", "Sum", 0, 8, 12),
        {"type": "metric", "x": 12, "y": 8, "width": 12, "height": 6, "properties": {
            "title": "EC2 CPU %", "region": REGION, "view": "timeSeries", "stat": "Average", "period": 60,
            "metrics": [["AWS/EC2", "CPUUtilization", "InstanceId", INSTANCE or "unknown"]]}},
        {"type": "log", "x": 0, "y": 14, "width": 24, "height": 7, "properties": {
            "title": "Bedrock invocation log (prompt/response metadata)", "region": REGION, "view": "table",
            "query": f"SOURCE '{INV_LOG_GROUP}' | fields @timestamp, requestId, modelId, "
                     "input.inputTokenCount as in_tok, output.outputTokenCount as out_tok | sort @timestamp desc | limit 25"}},
        {"type": "log", "x": 0, "y": 21, "width": 24, "height": 7, "properties": {
            "title": "App log from EC2 (/rescuegrid3d/app)", "region": REGION, "view": "table",
            "query": f"SOURCE '{APP_LOG_GROUP}' | fields @timestamp, @message | sort @timestamp desc | limit 40"}},
    ]}
    cw.put_dashboard(DashboardName=DASHBOARD, DashboardBody=json.dumps(body))


def setup() -> None:
    print("[1/4] log group", INV_LOG_GROUP)
    ensure_log_group(INV_LOG_GROUP)
    print("[2/4] IAM role", INV_ROLE, "(bedrock.amazonaws.com may write to that log group only)")
    arn = ensure_logging_role()
    print("[3/4] Bedrock model invocation logging -> CloudWatch (text only, images not stored)")
    enable_invocation_logging(arn)
    print("[4/4] CloudWatch dashboard", DASHBOARD)
    put_dashboard()
    print("\nDone. Run a mission so new calls get logged, then:  python scripts/deploy/aws_showcase.py report")
    print("Dashboard:", f"{CONSOLE}/cloudwatch/home?region={REGION}#dashboards/dashboard/{DASHBOARD}")


def teardown() -> None:
    try:
        cw.delete_dashboards(DashboardNames=[DASHBOARD])
        print("deleted dashboard", DASHBOARD)
    except ClientError as e:
        print("dashboard:", e.response["Error"]["Code"])
    if PREV_CFG.exists():
        bedrock.put_model_invocation_logging_configuration(loggingConfig=json.loads(PREV_CFG.read_text()))
        PREV_CFG.unlink()
        print("restored the account's previous Bedrock logging config")
    else:
        bedrock.delete_model_invocation_logging_configuration()
        print("disabled Bedrock invocation logging")
    try:
        iam.delete_role_policy(RoleName=INV_ROLE, PolicyName="write-invocation-logs")
        iam.delete_role(RoleName=INV_ROLE)
        print("deleted role", INV_ROLE)
    except ClientError as e:
        print("role:", e.response["Error"]["Code"])
    print(f"kept log group {INV_LOG_GROUP} (7-day retention); delete it in CloudWatch if you want it gone")


# ------------------------------------------------------------------ report
class Out:
    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, line: str = "") -> None:
        print(line)
        self.lines.append(line)

    def h(self, title: str, link: str | None = None) -> None:
        self("")
        self(f"## {title}")
        if link:
            self(f"Console: {link}")


def safe(out: Out, fn) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 — a missing permission must not hide the other sections
        out(f"  (unavailable: {type(e).__name__}: {str(e)[:160]})")


def report() -> None:
    out = Out()
    now = dt.datetime.now(dt.timezone.utc)
    out("# RESCUEGRID 3D: AWS evidence")
    out(f"Generated {now:%Y-%m-%d %H:%M UTC} · app {URL}")
    mission = {"id": None}

    def identity():
        i = sts.get_caller_identity()
        out(f"  account {i['Account']} · caller {i['Arn'].split('/')[-2] if '/' in i['Arn'] else i['Arn']} · region {REGION}")
    out.h("Identity")
    safe(out, identity)

    def app():
        st = requests.get(URL + "/api/system/status", timeout=10).json()
        b, s3s = st["bedrock"], st["s3"]
        out(f"  Bedrock: state {b['state']} · {b['calls_ok']} ok / {b['calls_failed']} failed · model {b['model_id']}")
        out(f"  S3: state {s3s['state']} · {s3s['uploads']} uploads this process · bucket {s3s['bucket']}")
        snap = requests.get(URL + "/api/mission", timeout=10)
        if snap.ok:
            mission["id"] = (snap.json().get("mission") or {}).get("mission_id")
        inv = requests.get(URL + "/api/ai/invocations", timeout=10).json()
        if mission["id"] is None and inv:
            mission["id"] = inv[-1].get("mission_id")
        out(f"  Mission {mission['id']} · {len(inv)} Bedrock calls recorded by the app:")
        for i in inv[-8:]:
            out(f"    {i['invocation_id']}  {i['kind']:<17} {i['status']:<8} {float(i.get('latency_ms') or 0):>7.0f} ms  "
                f"in {i.get('input_tokens')} / out {i.get('output_tokens')} tok  req {i.get('request_id')}")
    out.h("Running app (EC2 -> its own status API)", f"{URL}/api/ai/invocations")
    safe(out, app)

    def instance():
        r = ec2.describe_instances(InstanceIds=[INSTANCE])["Reservations"][0]["Instances"][0]
        prof = r.get("IamInstanceProfile", {}).get("Arn", "-").split("/")[-1]
        out(f"  {INSTANCE} · {r['InstanceType']} · {r['State']['Name']} · public IP {r.get('PublicIpAddress')}")
        out(f"  instance profile {prof} · IMDSv2 {r['MetadataOptions']['HttpTokens']} · launched {r['LaunchTime']:%Y-%m-%d %H:%M}")
        for g in r["SecurityGroups"]:
            sg = ec2.describe_security_groups(GroupIds=[g["GroupId"]])["SecurityGroups"][0]
            ports = [f"{p.get('FromPort')}/{p.get('IpProtocol')}" for p in sg["IpPermissions"]]
            out(f"  security group {sg['GroupName']}: inbound {', '.join(ports) or 'none'}")
    out.h("EC2", f"{CONSOLE}/ec2/home?region={REGION}#InstanceDetails:instanceId={INSTANCE}")
    safe(out, instance)

    def role():
        pol = iam.get_role_policy(RoleName=f"{NAME}-ec2", PolicyName=f"{NAME}-least-privilege")["PolicyDocument"]
        for st in pol["Statement"]:
            res = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
            out(f"  {st['Sid']}: {', '.join(st['Action'])}")
            for x in res:
                out(f"      on {x}")
    out.h("IAM role used by the server (no access keys on the instance)",
          f"https://console.aws.amazon.com/iam/home#/roles/details/{NAME}-ec2")
    safe(out, role)

    def metrics():
        start, total = now - dt.timedelta(hours=6), {}
        for d in bedrock_model_dims():
            for m, stat in (("Invocations", "Sum"), ("InvocationLatency", "Average"),
                            ("InputTokenCount", "Sum"), ("OutputTokenCount", "Sum"), ("InvocationClientErrors", "Sum")):
                pts = cw.get_metric_statistics(Namespace="AWS/Bedrock", MetricName=m, StartTime=start, EndTime=now,
                                               Period=21600, Statistics=[stat],
                                               Dimensions=[{"Name": "ModelId", "Value": d}])["Datapoints"]
                v = pts[0][stat] if pts else 0
                total[(d, m)] = v
            out(f"  {d} (last 6 h): {total[(d, 'Invocations')]:.0f} invocations · avg latency "
                f"{total[(d, 'InvocationLatency')]:.0f} ms · {total[(d, 'InputTokenCount')]:.0f} in / "
                f"{total[(d, 'OutputTokenCount')]:.0f} out tokens · {total[(d, 'InvocationClientErrors')]:.0f} client errors")
        out("  (These numbers come from AWS, not from the app. Metrics can lag a few minutes.)")
    out.h("CloudWatch metrics, namespace AWS/Bedrock",
          f"{CONSOLE}/cloudwatch/home?region={REGION}#dashboards/dashboard/{DASHBOARD}")
    safe(out, metrics)

    def inv_logs():
        c = bedrock.get_model_invocation_logging_configuration().get("loggingConfig")
        if not c:
            out("  invocation logging is OFF. Run `aws_showcase.py setup` to turn it on.")
            return
        out(f"  invocation logging ON -> {c.get('cloudWatchConfig', {}).get('logGroupName')}")
        ev, kw = [], {"logGroupName": INV_LOG_GROUP, "startTime": int((now - dt.timedelta(hours=6)).timestamp() * 1000)}
        while len(ev) < 2000:  # filter_log_events returns oldest first, so page through to reach the newest
            r = logs.filter_log_events(**kw)
            ev += r.get("events", [])
            if not r.get("nextToken"):
                break
            kw["nextToken"] = r["nextToken"]
        ev.sort(key=lambda e: e["timestamp"])
        out(f"  {len(ev)} logged calls in the last 6 h (newest 5):")
        for e in ev[-5:]:
            j = json.loads(e["message"])
            out(f"    {j.get('timestamp')}  req {j.get('requestId')}  {j.get('operation')}  "
                f"in {j.get('input', {}).get('inputTokenCount')} / out {j.get('output', {}).get('outputTokenCount')} tok")
        out("  Match a request ID here with the one in the app's AI inspect tab.")
    out.h("Bedrock model invocation logs", f"{CONSOLE}/cloudwatch/home?region={REGION}#logsV2:log-groups/log-group/{quote(quote(INV_LOG_GROUP, safe=''), safe='')}")
    safe(out, inv_logs)

    def bucket():
        enc = s3c.get_bucket_encryption(Bucket=BUCKET)["ServerSideEncryptionConfiguration"]["Rules"][0]
        pab = s3c.get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
        out(f"  encryption {enc['ApplyServerSideEncryptionByDefault']['SSEAlgorithm']} · block public access "
            f"{'ON' if all(pab.values()) else 'PARTIAL'}")
        prefix = f"missions/{mission['id']}/" if mission["id"] else "missions/"
        counts: dict[str, int] = {}
        sample: dict[str, str] = {}
        for page in s3c.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
            for o in page.get("Contents", []):
                parts = o["Key"].split("/")
                kind = parts[2] if len(parts) > 3 else parts[-1]
                counts[kind] = counts.get(kind, 0) + 1
                sample.setdefault(kind, o["Key"])
        out(f"  s3://{BUCKET}/{prefix}")
        for k, n in sorted(counts.items()):
            out(f"    {k:<14} {n:>5} objects   e.g. {sample[k]}")
    out.h("S3 evidence bucket",
          f"https://s3.console.aws.amazon.com/s3/buckets/{BUCKET}?region={REGION}&prefix=missions/")
    safe(out, bucket)

    def app_logs():
        streams = logs.describe_log_streams(logGroupName=APP_LOG_GROUP, orderBy="LastEventTime", descending=True, limit=5)["logStreams"]
        stream = next((x["logStreamName"] for x in streams if x["logStreamName"] == INSTANCE), streams[0]["logStreamName"] if streams else None)
        if not stream:
            out("  no log streams yet")
            return
        ev = logs.get_log_events(logGroupName=APP_LOG_GROUP, logStreamName=stream, startFromHead=False, limit=200)["events"]
        interesting = [e for e in ev if "/api/incidents" in e["message"] or "/api/routes" in e["message"]
                       or "/api/briefings" in e["message"] or "ready" in e["message"]] or ev
        out(f"  stream {stream} (named after the instance ID). Newest decision/briefing lines:")
        for e in interesting[-6:]:
            t = dt.datetime.fromtimestamp(e["timestamp"] / 1000, dt.timezone.utc)
            out(f"    {t:%H:%M:%S}  " + e["message"].strip()[:140])
    out.h("CloudWatch Logs from the instance",
          f"{CONSOLE}/cloudwatch/home?region={REGION}#logsV2:log-groups/log-group/{quote(quote(APP_LOG_GROUP, safe=''), safe='')}")
    safe(out, app_logs)

    path = ROOT / "docs" / "aws_showcase_report.md"
    path.write_text("\n".join(out.lines) + "\n", encoding="utf-8")
    print(f"\nwritten {path.relative_to(ROOT)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"setup": setup, "report": report, "teardown": teardown}.get(cmd, lambda: sys.exit(__doc__))()
