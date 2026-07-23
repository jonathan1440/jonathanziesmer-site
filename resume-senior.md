---
title: Jonathan Ziesmer
location: Chattanooga, Tennessee
email: jztrailg@gmail.com
phone: (423) 650-8021
linkedin: linkedin.com/in/jonathan-ziesmer/
---

**SUMMARY**

Software engineer with five years of production experience in Python, TypeScript, and AWS serverless architecture. Built the automated ETL pipeline that became the standard onboarding path for a multi-tenant SaaS platform serving 600+ clients; currently own enterprise integrations and CI/CD platform standards at Point Loma Nazarene University. Experienced leading cross-functional teams and owning systems from design through production.

---

**SKILLS**

**Languages:** Python, TypeScript, JavaScript, Java, Groovy, SQL (PostgreSQL)
**AWS:** Lambda, Glue, Step Functions, EventBridge, API Gateway, S3, SQS/SNS, RDS, DynamoDB, IAM (OIDC), CloudWatch, CDK, CloudFormation
**Platforms & Practices:** Workday Studio & EIB, Salesforce, Vue, React, GitHub Actions, CI/CD, Infrastructure as Code, Test-Driven Development

---

**WORK EXPERIENCE**

Point Loma Nazarene University | Jan 2026 - Present
:   Software Engineer | Remote

* Built two daily Workday integrations (Studio and EIB) extracting 3,000+ student records per run: automated test-score delivery to a State of California grant compliance endpoint and a 90+ field student/academic profile feed to Pathify, replacing manual exports with zero failed runs to date.
* Led BitBucket-to-GitHub platform consolidation (8 repositories) and standardized deployment across 30+ organization repos with a reusable GitHub Actions workflow, AWS OIDC federation replacing long-lived credentials, and required PR and production-deploy approval gates.
* Introduced CI-gated unit and integration test suites for three previously untested services (Python, Java), prioritizing behavioral verification of core paths over coverage metrics; failing tests block deployment and regularly catch regressions before release.
* Designed and taught the engineering team's agentic AI development workflow (spec, plan, build, review, fix) in Cursor, structured for future GitHub-triggered automation.

CampLife | Aug 2021 - Jun 2025
:   Full-Stack Software Engineer | Remote

* Architected automated ETL pipeline for customer onboarding using Python, AWS Lambda, and Glue: multi-stage schema detection and validation, data normalization, and fuzzy-match deduplication across inconsistent legacy exports. Migrated heavy processing from Lambda to Glue to handle 1M+ record datasets. Cut onboarding time from 3-5 days to 4-6 hours at 99%+ data accuracy across 180+ clients, reducing import-related support tickets by 70%.
* Led cross-functional team resolving issues across the stack of a multi-tenant SaaS platform serving 600+ RV parks: database schemas (PostgreSQL, Hibernate), REST APIs (Groovy), payment processor integrations, and UI components (Vue).
* Spearheaded an inventory lifecycle tracking feature, leading a 2-person team across PostgreSQL schema design, Groovy REST APIs, and Vue UI alongside business stakeholders.
* Analyzed reservation and occupancy data with Python (Pandas, NumPy, Plotly); findings drove a reengineered occupancy-rules feature launch and industry reports presented alongside the CEO and COO at the 2024 CampEx conference.

---

**PROJECTS**

**Finish Line Photo Extractor**

* Architected a CDK-deployed video pipeline (Step Functions, ECS Fargate, ffmpeg, S3, DynamoDB) syncing finish-line footage to race results and extracting labeled finisher photos. Processed 1TB+ across 35 races (70,000 photos), cutting per-race photography cost from $2,000 to $20; hired and managed a contractor for the operator UI.

---

**EDUCATION**

Southern Adventist University | Jul 2018 - Aug 2021
:   B.S. Computer Science; graduate coursework in distributed systems | Chattanooga, Tennessee
