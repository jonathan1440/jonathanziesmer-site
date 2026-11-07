export const skillGroups = [
  {
    label: 'Languages',
    items: ['Python', 'TypeScript', 'JavaScript', 'Java', 'Groovy', 'SQL (PostgreSQL)'],
  },
  {
    label: 'AWS',
    items: [
      'Lambda',
      'Glue',
      'Step Functions',
      'EventBridge',
      'API Gateway',
      'S3',
      'SQS/SNS',
      'RDS',
      'DynamoDB',
      'IAM (OIDC)',
      'CloudWatch',
      'CDK',
      'CloudFormation',
    ],
  },
  {
    label: 'Platforms & Practices',
    items: [
      'Workday Studio & EIB',
      'Salesforce',
      'Vue',
      'React',
      'GitHub Actions',
      'CI/CD',
      'Infrastructure as Code',
      'Test-Driven Development',
    ],
  },
] as const;
