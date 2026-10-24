"""Print EC2 instance status, recent CPU, credit balance and the tail of the app log."""
import datetime as dt
import json
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]
iid = json.loads((ROOT / "data" / "deployment.json").read_text())["instance_id"]
s = boto3.Session(region_name="us-east-1")
ec2, cw, logs = s.client("ec2"), s.client("cloudwatch"), s.client("logs")

st = ec2.describe_instance_status(InstanceIds=[iid], IncludeAllInstances=True)["InstanceStatuses"][0]
print(iid, st["InstanceState"]["Name"], "instance:", st.get("InstanceStatus", {}).get("Status"), "system:", st.get("SystemStatus", {}).get("Status"))
now = dt.datetime.now(dt.timezone.utc)
for metric in ("CPUUtilization", "CPUCreditBalance"):
    pts = cw.get_metric_statistics(Namespace="AWS/EC2", MetricName=metric, Dimensions=[{"Name": "InstanceId", "Value": iid}],
                                   StartTime=now - dt.timedelta(minutes=60), EndTime=now, Period=300, Statistics=["Average", "Maximum"])
    print(metric, [(p["Timestamp"].strftime("%H:%M"), round(p["Average"]), round(p["Maximum"])) for p in sorted(pts["Datapoints"], key=lambda p: p["Timestamp"])])
ev = logs.filter_log_events(logGroupName="/rescuegrid3d/app", startTime=int((now - dt.timedelta(minutes=30)).timestamp() * 1000)).get("events", [])
print(len(ev), "log lines in last 30 min; tail:")
for e in ev[-25:]:
    print("  ", dt.datetime.fromtimestamp(e["timestamp"] / 1000, dt.timezone.utc).strftime("%H:%M:%S"), e["message"].strip()[:180])
