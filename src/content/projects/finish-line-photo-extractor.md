---
title: Finish Line Photo Extractor
summary: CDK pipeline that syncs finish-line video to race results and extracts labeled finisher photos.
problem: A race company was paying about $2,000 a race for a photographer, so operators mark the first finisher and the pipeline (Step Functions, ECS Fargate, ffmpeg) turns CSV or Race Roster times into clips and JPEGs — 1TB+ across 35 races, about 70,000 photos, about $20 a race. I built the pipeline and cloud architecture and hired a contractor for the original operator UI.
stack:
  - AWS CDK
  - Step Functions
  - ECS Fargate
  - ffmpeg
  - Python
  - FastAPI
  - S3
  - DynamoDB
featured: true
order: 1
---
