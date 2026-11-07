---
title: Full-Stack Software Engineer
company: CampLife
dates: Aug 2021 – Jun 2025
location: Chattanooga, Tennessee · Remote
stack:
  - Python
  - AWS Lambda
  - AWS Glue
  - PostgreSQL
  - Hibernate
  - Groovy
  - Vue
  - Pandas
  - Drools
bullets:
  - "Architected the ETL pipeline that became the standard onboarding path. Python detects columns across Newbook, RMS, paper-ledger, and spreadsheet exports, validates reservation rules, normalizes values, and fuzzy-matches duplicates into PostgreSQL, with row-level reports on failure. Lambda orchestrates; Glue took the heavy transform after a 1M+ record file timed Lambda out. Onboarding fell from 3–5 days to 4–6 hours at 99%+ accuracy across 180+ parks, and import-related support tickets dropped 70%."
  - "Led a cross-functional backlog team on a multi-tenant platform serving 600+ RV parks. Weekly triage favored high-impact, low-effort fixes. Work crossed PostgreSQL and Hibernate schemas, Groovy REST APIs, payment-processor integrations, Vue UI, and live database migrations."
  - "Led a 2-person team on inventory and ticket lifecycle tracking: PostgreSQL schemas with Hibernate, Groovy REST APIs from OpenAPI specs, and a Vue UI, with business stakeholders in the loop. When a contractual deadline narrowed the work to ticketing, the schema stayed, generic inventory endpoints closed, and ticket states were hard-coded so it could ship in the remaining month."
  - "Analyzed reservation and occupancy data across 600+ parks with Python (psycopg2, Pandas, NumPy, Plotly). In that analysis, parks that adjusted weekend pricing with occupancy had 15–20% higher revenue than parks with static pricing. The finding drove a Groovy and Drools occupancy-rules feature, and the reports were presented with the CEO and COO at the 2024 CampEx session Making Business Decisions Driven by Data."
featured: false
kind: role
order: 2
---
