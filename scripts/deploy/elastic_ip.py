"""Give the running rescuegrid3d instance a stable Elastic IP (idempotent)."""
import json
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]
ec2 = boto3.client("ec2", region_name="us-east-1")
inst = [i for r in ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": ["rescuegrid3d"]},
                                                   {"Name": "instance-state-name", "Values": ["running", "pending"]}])["Reservations"]
        for i in r["Instances"]]
iid = sorted(inst, key=lambda i: i["LaunchTime"])[-1]["InstanceId"]
addrs = ec2.describe_addresses(Filters=[{"Name": "tag:Name", "Values": ["rescuegrid3d"]}])["Addresses"]
if addrs:
    alloc = addrs[0]["AllocationId"]
    ip = addrs[0]["PublicIp"]
else:
    a = ec2.allocate_address(Domain="vpc", TagSpecifications=[{"ResourceType": "elastic-ip", "Tags": [{"Key": "Name", "Value": "rescuegrid3d"}]}])
    alloc, ip = a["AllocationId"], a["PublicIp"]
ec2.associate_address(AllocationId=alloc, InstanceId=iid, AllowReassociation=True)
url = f"http://{ip}"
p = ROOT / "data" / "deployment.json"
d = json.loads(p.read_text()) if p.exists() else {}
d.update({"url": url, "instance_id": iid, "elastic_ip": ip})
p.write_text(json.dumps(d, indent=2))
print("stable URL", url, "->", iid)
