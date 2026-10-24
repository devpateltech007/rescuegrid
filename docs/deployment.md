# Deployment (AWS)

## What gets created (`scripts/deploy/deploy.py`, idempotent)

| Resource | Name | Notes |
|---|---|---|
| S3 bucket | `rescuegrid3d-<account>-us-east-1` | Public access blocked, SSE-S3. Prefixes `missions/` (evidence, scan chunks, briefings) and `releases/` (app tarball) |
| IAM role + instance profile | `rescuegrid3d-ec2` | Inline policy: `bedrock:InvokeModel`/`Converse` on the selected inference profile + its foundation model only; `s3:GetObject/PutObject` on `missions/*` and `releases/*` only; CloudWatch Logs on `/rescuegrid3d/*` only |
| Security group | `rescuegrid3d-web` | Inbound TCP 80 only, no SSH |
| CloudWatch log group | `/rescuegrid3d/app` | 7-day retention; the CloudWatch agent ships `/var/log/rescuegrid.log` |
| EC2 | `rescuegrid3d` (t3.large, AL2023, IMDSv2 required, encrypted gp3) | user-data installs Python 3.11, nginx, the app and a systemd unit; nginx proxies `/` and `/ws/` to uvicorn |

The instance gets credentials only from its role. No access keys are ever copied to it.

## Run

```cmd
call .secrets\aws.cmd            &rem or any AWS profile with admin rights in the hackathon account
scripts\build_frontend.cmd
.venv\Scripts\python.exe scripts\build_manifest.py
.venv\Scripts\python.exe scripts\deploy\deploy.py
rem wait ~4-6 min for bootstrap, then:
.venv\Scripts\python.exe scripts\smoke_api.py http://<public-dns>
```

The URL is written to `data/deployment.json`. Re-running `deploy.py` uploads a new release and
replaces the instance.

## Operations

- Logs: CloudWatch → `/rescuegrid3d/app` → stream = instance id.
- Health: `GET /health`, `GET /api/system/status` (Bedrock/S3 state, never secrets).
- Teardown: terminate the instance tagged `Name=rescuegrid3d`, delete the security group, the
  instance profile and role, and empty and delete the bucket.
