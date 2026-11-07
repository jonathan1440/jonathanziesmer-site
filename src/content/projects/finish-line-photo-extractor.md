---
title: Finish Line Photo Extractor
summary: CDK-deployed pipeline that syncs finish-line footage to race results and extracts labeled finisher photos.
problem: Manual finish-line photography cost about $2,000 a race. The pipeline (Step Functions, ECS Fargate, ffmpeg, S3, DynamoDB) processed 1TB+ across 35 races — 70,000 photos — cut that cost to $20, and I hired a contractor to build the operator UI.
stack:
  - AWS CDK
  - Step Functions
  - ECS Fargate
  - ffmpeg
  - S3
  - DynamoDB
featured: true
order: 1
---
