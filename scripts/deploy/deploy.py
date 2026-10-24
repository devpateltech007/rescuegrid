"""Idempotent AWS deployment of RESCUEGRID 3D to a single EC2 instance (AWS CLI equivalent via boto3).

Creates / reuses:
  * S3 bucket (already created in Task 1) — release tarball + evidence prefixes
  * IAM role + instance profile "rescuegrid3d-ec2" with least privilege:
      bedrock:InvokeModel / Converse on the selected inference profile + its foundation models,
      s3 Get/Put on the bucket's missions/ and releases/ prefixes, CloudWatch Logs for its log group
  * Security group "rescuegrid3d-web": port 80 open (demo), no SSH (use SSM if needed)
  * CloudWatch log group /rescuegrid3d/app
  * t3.large Amazon Linux 2023 instance whose user-data installs Python 3.11, nginx, the app
    and a systemd unit; nginx serves the built frontend via uvicorn and proxies /ws.
The instance role replaces any local credentials — no keys are copied to the instance.

Usage: python scripts/deploy/deploy.py  (prints the public URL)
"""
from __future__ import annotations

import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]
REGION = "us-east-1"
NAME = "rescuegrid3d"
cfg = json.loads((ROOT / "data" / "aws_config.json").read_text())
BUCKET = cfg["bucket"]
MODEL = cfg["bedrock_model_id"]
ACCOUNT = cfg["account"]

s = boto3.Session(region_name=REGION)
ec2, iam, s3c, ssm, logs = (s.client(x) for x in ("ec2", "iam", "s3", "ssm", "logs"))

INCLUDE = ["backend/app", "backend/requirements.txt", "frontend/dist", "data/geography", "data/terrain",
           "data/road_graph", "data/imagery", "data/scenarios", "data/aws_config.json", "data/manifest.json", "scripts/smoke_api.py"]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}


def build_release() -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in INCLUDE:
            p = ROOT / rel
            if not p.exists():
                continue
            for f in ([p] if p.is_file() else sorted(p.rglob("*"))):
                if f.is_file() and not (set(f.parts) & EXCLUDE_PARTS):
                    tar.add(f, arcname=str(f.relative_to(ROOT)).replace("\\", "/"))
    key = f"releases/{NAME}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    s3c.put_object(Bucket=BUCKET, Key=key, Body=buf.getvalue(), ServerSideEncryption="AES256")
    print(f"[1/6] release uploaded s3://{BUCKET}/{key} ({len(buf.getvalue()) / 1e6:.1f} MB)")
    return key


def role() -> str:
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    try:
        iam.create_role(RoleName=f"{NAME}-ec2", AssumeRolePolicyDocument=json.dumps(trust),
                        Description="RESCUEGRID 3D app server (least privilege)")
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    model_tail = MODEL.split(".", 1)[1] if MODEL.startswith("us.") else MODEL
    policy = {"Version": "2012-10-17", "Statement": [
        {"Sid": "BedrockSelectedModel", "Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:Converse"],
         "Resource": [f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/{MODEL}",
                      f"arn:aws:bedrock:*::foundation-model/{model_tail}"]},
        {"Sid": "EvidenceBucket", "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
         "Resource": [f"arn:aws:s3:::{BUCKET}/missions/*", f"arn:aws:s3:::{BUCKET}/releases/*"]},
        {"Sid": "Logs", "Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"],
         "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/{NAME}/*"},
    ]}
    iam.put_role_policy(RoleName=f"{NAME}-ec2", PolicyName=f"{NAME}-least-privilege", PolicyDocument=json.dumps(policy))
    try:
        iam.create_instance_profile(InstanceProfileName=f"{NAME}-ec2")
        iam.add_role_to_instance_profile(InstanceProfileName=f"{NAME}-ec2", RoleName=f"{NAME}-ec2")
        time.sleep(12)  # IAM propagation
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    print(f"[2/6] IAM role/instance profile {NAME}-ec2 ready (Bedrock {MODEL}, S3 {BUCKET}/missions+releases, Logs)")
    return f"{NAME}-ec2"


def security_group() -> str:
    vpc = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    g = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [f"{NAME}-web"]}, {"Name": "vpc-id", "Values": [vpc]}])["SecurityGroups"]
    if g:
        sg = g[0]["GroupId"]
    else:
        sg = ec2.create_security_group(GroupName=f"{NAME}-web", Description="RESCUEGRID 3D web (HTTP only)", VpcId=vpc)["GroupId"]
        ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "demo HTTP"}]}])
    print(f"[3/6] security group {sg} (inbound 80 only)")
    return sg


def log_group():
    try:
        logs.create_log_group(logGroupName=f"/{NAME}/app")
        logs.put_retention_policy(logGroupName=f"/{NAME}/app", retentionInDays=7)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    print(f"[4/6] CloudWatch log group /{NAME}/app")


USER_DATA = r"""#!/bin/bash
set -euxo pipefail
dnf install -y python3.11 python3.11-pip nginx amazon-cloudwatch-agent tar gzip
mkdir -p /opt/rescuegrid && cd /opt/rescuegrid
aws s3 cp s3://__BUCKET__/__KEY__ release.tar.gz --region us-east-1
tar xzf release.tar.gz && rm release.tar.gz
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt
mkdir -p data/runtime && chown -R ec2-user:ec2-user /opt/rescuegrid
cat >/etc/systemd/system/rescuegrid.service <<'EOF'
[Unit]
Description=RESCUEGRID 3D
After=network-online.target
[Service]
User=ec2-user
WorkingDirectory=/opt/rescuegrid
Environment=AWS_REGION=us-east-1
Environment=RESCUEGRID_BUCKET=__BUCKET__
Environment=RESCUEGRID_BEDROCK_MODEL=__MODEL__
ExecStart=/opt/rescuegrid/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --log-level info
StandardOutput=append:/var/log/rescuegrid.log
StandardError=append:/var/log/rescuegrid.log
Restart=always
[Install]
WantedBy=multi-user.target
EOF
cat >/etc/nginx/conf.d/rescuegrid.conf <<'EOF'
server {
  listen 80 default_server;
  client_max_body_size 5m;
  gzip on; gzip_types application/json application/javascript text/css application/octet-stream;
  location /ws/ { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_read_timeout 3600s; }
  location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_read_timeout 180s; }
}
EOF
sed -i 's/listen       80;/listen       8080;/; s/listen       \[::\]:80;/listen       [::]:8080;/' /etc/nginx/nginx.conf || true
cat >/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'EOF'
{"logs":{"logs_collected":{"files":{"collect_list":[{"file_path":"/var/log/rescuegrid.log","log_group_name":"/rescuegrid3d/app","log_stream_name":"{instance_id}"}]}}}}
EOF
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json || true
touch /var/log/rescuegrid.log && chown ec2-user /var/log/rescuegrid.log
systemctl daemon-reload && systemctl enable --now rescuegrid nginx
"""


def instance(profile: str, sg: str, key: str) -> str:
    existing = ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [NAME]}, {"Name": "instance-state-name", "Values": ["pending", "running"]}])
    for r in existing["Reservations"]:
        for i in r["Instances"]:
            print(f"[5/6] terminating previous instance {i['InstanceId']} (replaced by new release)")
            ec2.terminate_instances(InstanceIds=[i["InstanceId"]])
    ami = ssm.get_parameter(Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64")["Parameter"]["Value"]
    ud = USER_DATA.replace("__BUCKET__", BUCKET).replace("__KEY__", key).replace("__MODEL__", MODEL)
    for attempt in range(5):
        try:
            r = ec2.run_instances(ImageId=ami, InstanceType=os.getenv("RG_INSTANCE_TYPE", "t3.large"), MinCount=1, MaxCount=1,
                                  IamInstanceProfile={"Name": profile}, SecurityGroupIds=[sg], UserData=ud,
                                  MetadataOptions={"HttpTokens": "required"},
                                  BlockDeviceMappings=[{"DeviceName": "/dev/xvda", "Ebs": {"VolumeSize": 20, "VolumeType": "gp3", "Encrypted": True}}],
                                  TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": NAME}, {"Key": "project", "Value": "rescuegrid3d"}]}])
            break
        except Exception as e:  # noqa: BLE001 — instance profile propagation
            if "Invalid IAM Instance Profile" in str(e) and attempt < 4:
                time.sleep(10)
                continue
            raise
    iid = r["Instances"][0]["InstanceId"]
    ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
    d = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
    print(f"[5/6] instance {iid} running ({d['InstanceType']}, {ami})")
    return d.get("PublicDnsName") or d.get("PublicIpAddress")


def main():
    key = build_release()
    profile = role()
    sg = security_group()
    log_group()
    host = instance(profile, sg, key)
    url = f"http://{host}"
    (ROOT / "data" / "deployment.json").write_text(json.dumps({"url": url, "release": key, "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2))
    print(f"[6/6] bootstrapping (pip install ~3-5 min). URL: {url}")
    import runpy
    runpy.run_path(str(Path(__file__).with_name("elastic_ip.py")))


if __name__ == "__main__":
    sys.exit(main())
