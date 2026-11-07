---
title: ETL Pipeline for Customer Onboarding
summary: The automated onboarding path for CampLife parks with inconsistent legacy exports.
problem: Python detects columns across Newbook, RMS, ledger, and spreadsheet exports, validates reservation rules, normalizes values, and fuzzy-matches duplicates into PostgreSQL, with row-level reports when a file fails. Lambda orchestrates and Glue does the heavy work after a 1M+ record file timed out; onboarding went from 3–5 days to 4–6 hours at 99%+ accuracy across 180+ parks, and import tickets fell 70%.
stack:
  - Python
  - AWS Lambda
  - AWS Glue
  - PostgreSQL
  - CloudWatch
featured: true
order: 6
---
