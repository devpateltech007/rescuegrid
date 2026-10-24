# RESCUEGRID 3D: AWS evidence
Generated 2026-10-24 08:30 UTC · app http://32.195.112.28

## Identity
  account 663748689981 · caller WSParticipantRole · region us-east-1

## Running app (EC2 -> its own status API)
Console: http://32.195.112.28/api/ai/invocations
  Bedrock: state OK · 22 ok / 0 failed · model us.anthropic.claude-sonnet-4-5-20250929-v1:0
  S3: state OK · 290 uploads this process · bucket rescuegrid3d-663748689981-us-east-1
  Mission M-6CF418 · 5 Bedrock calls recorded by the app:
    AI-0c77c1f1  HAZARD_ANALYSIS   SUCCESS     7702 ms  in 1839 / out 385 tok  req 6d6af583-e830-4302-abca-aeac821a8d57
    AI-8ccc2616  HAZARD_ANALYSIS   SUCCESS    12102 ms  in 2100 / out 464 tok  req de5641c7-f3b1-4092-8e12-2a600406c40b
    AI-9748975f  HAZARD_ANALYSIS   SUCCESS     9293 ms  in 1838 / out 433 tok  req 7c103e40-2edb-46ec-be54-70e41f9a0dda
    AI-93314cb5  HAZARD_ANALYSIS   SUCCESS     9741 ms  in 1946 / out 450 tok  req 43437bfb-6220-46b4-bf0a-2145d116cd77
    AI-1d6600d1  MISSION_BRIEFING  SUCCESS    17012 ms  in 2225 / out 1010 tok  req 96c42a66-a119-4b47-8f2a-a4467e4f6333

## EC2
Console: https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#InstanceDetails:instanceId=i-014a4951f0f22c1bd
  i-014a4951f0f22c1bd · t3.large · running · public IP 32.195.112.28
  instance profile rescuegrid3d-ec2 · IMDSv2 required · launched 2026-10-24 06:54
  security group rescuegrid3d-web: inbound 80/tcp

## IAM role used by the server (no access keys on the instance)
Console: https://console.aws.amazon.com/iam/home#/roles/details/rescuegrid3d-ec2
  BedrockSelectedModel: bedrock:InvokeModel, bedrock:Converse
      on arn:aws:bedrock:us-east-1:663748689981:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0
      on arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0
  EvidenceBucket: s3:GetObject, s3:PutObject
      on arn:aws:s3:::rescuegrid3d-663748689981-us-east-1/missions/*
      on arn:aws:s3:::rescuegrid3d-663748689981-us-east-1/releases/*
  Logs: logs:CreateLogStream, logs:PutLogEvents, logs:DescribeLogStreams
      on arn:aws:logs:us-east-1:663748689981:log-group:/rescuegrid3d/*

## CloudWatch metrics, namespace AWS/Bedrock
Console: https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/rescuegrid3d
  us.anthropic.claude-sonnet-4-5-20250929-v1:0 (last 6 h): 161 invocations · avg latency 6008 ms · 337926 in / 59160 out tokens · 0 client errors
  (These numbers come from AWS, not from the app. Metrics can lag a few minutes.)

## Bedrock model invocation logs
Console: https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/%252Frescuegrid3d%252Fbedrock-invocations
  invocation logging ON -> /rescuegrid3d/bedrock-invocations
  8 logged calls in the last 6 h (newest 5):
    2026-10-24T08:26:03Z  req 6d6af583-e830-4302-abca-aeac821a8d57  Converse  in 1839 / out 385 tok
    2026-10-24T08:26:19Z  req de5641c7-f3b1-4092-8e12-2a600406c40b  Converse  in 2100 / out 464 tok
    2026-10-24T08:27:08Z  req 7c103e40-2edb-46ec-be54-70e41f9a0dda  Converse  in 1838 / out 433 tok
    2026-10-24T08:27:32Z  req 43437bfb-6220-46b4-bf0a-2145d116cd77  Converse  in 1946 / out 450 tok
    2026-10-24T08:27:47Z  req 96c42a66-a119-4b47-8f2a-a4467e4f6333  Converse  in 2225 / out 1010 tok
  Match a request ID here with the one in the app's AI inspect tab.

## S3 evidence bucket
Console: https://s3.console.aws.amazon.com/s3/buckets/rescuegrid3d-663748689981-us-east-1?region=us-east-1&prefix=missions/
  encryption AES256 · block public access ON
  s3://rescuegrid3d-663748689981-us-east-1/missions/M-6CF418/
    briefings          1 objects   e.g. missions/M-6CF418/briefings/BRF-C492BF.json
    observations       4 objects   e.g. missions/M-6CF418/observations/OBS-C9F502.jpg
    scans             77 objects   e.g. missions/M-6CF418/scans/ALPHA-0025.npy

## CloudWatch Logs from the instance
Console: https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups/log-group/%252Frescuegrid3d%252Fapp
  stream i-014a4951f0f22c1bd (named after the instance ID). Newest decision/briefing lines:
    08:26:51  INFO:     127.0.0.1:59556 - "POST /api/incidents/INC-F7836/verify HTTP/1.1" 200 OK
    08:27:47  INFO:     127.0.0.1:34294 - "POST /api/incidents/INC-25DDD/verify HTTP/1.1" 200 OK
    08:27:50  INFO:     127.0.0.1:50242 - "POST /api/routes/RT-89e13cd2/approve HTTP/1.1" 200 OK
    08:28:05  INFO:     127.0.0.1:50256 - "POST /api/briefings/generate HTTP/1.1" 200 OK
