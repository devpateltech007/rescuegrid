# Showing the AWS side to judges

`scripts\aws_showcase.cmd` loads the credentials from `.secrets\aws.cmd` and runs `scripts/deploy/aws_showcase.py`.

| Command | What it does |
|---|---|
| `scripts\aws_showcase.cmd setup` | Turns on Bedrock model invocation logging to CloudWatch log group `/rescuegrid3d/bedrock-invocations` (text only, images are not stored). Creates IAM role `rescuegrid3d-bedrock-logging`, which can write only to that log group, and the CloudWatch dashboard `rescuegrid3d`. Safe to re-run. |
| `scripts\aws_showcase.cmd report` | Pulls live evidence from the app, EC2, IAM, CloudWatch metrics, invocation logs, S3 and app logs, prints it with console links, and writes `docs/aws_showcase_report.md`. Read-only. |
| `scripts\aws_showcase.cmd teardown` | Deletes the dashboard and the logging role, and turns invocation logging off (or restores the account's earlier setting). |

## Before judging

1. Run `setup` once. It's already done for the current account.
2. Run one full mission on http://32.195.112.28 so the metrics and logs contain fresh calls.
3. Run `report` and keep `docs/aws_showcase_report.md` open as a cheat sheet.
4. Open these tabs in **us-east-1**:
   - the app
   - the CloudWatch dashboard `rescuegrid3d`
   - the S3 bucket at `missions/<mission id>/`
   - IAM role `rescuegrid3d-ec2`

## 60-second walkthrough

| Step | Screen | Say |
|---|---|---|
| 1 | App → **Route & brief** → Generate briefing, then **AI inspect** | "That briefing was a live Claude Sonnet 4.5 call on Bedrock. Here's its latency, token count and AWS request ID." |
| 2 | CloudWatch dashboard `rescuegrid3d` | "These are AWS's own Bedrock metrics: invocations, latency, tokens. The table below is Bedrock's invocation log. The same request ID appears here." |
| 3 | Dashboard, app log panel | "This is the server's log, shipped from EC2 by the CloudWatch agent." |
| 4 | S3 `missions/<id>/observations/` | "This is the exact drone frame Claude analyzed. Lidar scans and the briefing JSON sit next to it. The bucket is encrypted and blocks public access." |
| 5 | IAM role `rescuegrid3d-ec2` → policy | "The server has no access keys. Its role can call only this one model, write only under this bucket path, and write only to its log group." |

Metrics can lag by 1–3 minutes, so show the dashboard last if the run was just now.
