"""Check which AWS actions the current credentials allow (read-only probes + IAM simulation)."""
import json
import sys

import boto3

s = boto3.Session(region_name="us-east-1")
ident = s.client("sts").get_caller_identity()
print("identity", ident["Arn"])
res = {}
for name, fn in {
    "ec2:DescribeInstances": lambda: s.client("ec2").describe_instances(MaxResults=5),
    "ec2:DescribeImages(al2023)": lambda: s.client("ssm").get_parameter(Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"),
    "iam:ListRoles": lambda: s.client("iam").list_roles(MaxItems=3),
    "iam:ListInstanceProfiles": lambda: s.client("iam").list_instance_profiles(MaxItems=3),
    "logs:DescribeLogGroups": lambda: s.client("logs").describe_log_groups(limit=1),
    "s3:ListBucket": lambda: s.client("s3").list_objects_v2(Bucket="rescuegrid3d-663748689981-us-east-1", MaxKeys=1),
}.items():
    try:
        out = fn()
        res[name] = "OK"
        if name.startswith("ec2:DescribeImages"):
            res["al2023_ami"] = out["Parameter"]["Value"]
    except Exception as e:  # noqa: BLE001
        res[name] = f"DENIED/ERR: {str(e)[:140]}"
try:
    sim = s.client("iam").simulate_principal_policy(
        PolicySourceArn=f"arn:aws:iam::{ident['Account']}:role/WSParticipantRole",
        ActionNames=["iam:CreateRole", "iam:PassRole", "iam:CreateInstanceProfile", "ec2:RunInstances",
                     "ec2:CreateSecurityGroup", "ec2:AuthorizeSecurityGroupIngress", "ssm:SendCommand"])
    for r in sim["EvaluationResults"]:
        res["sim:" + r["EvalActionName"]] = r["EvalDecision"]
except Exception as e:  # noqa: BLE001
    res["iam:SimulatePrincipalPolicy"] = f"ERR: {str(e)[:140]}"
print(json.dumps(res, indent=1))
