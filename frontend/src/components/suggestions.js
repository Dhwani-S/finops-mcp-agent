/**
 * Static suggestion prompts extracted from PRD use cases.
 * Grouped by category for potential future filtering.
 */
const SUGGESTIONS = [
  // UC-001: Cost Visibility
  'Show me AWS spend by service for last month',
  'What are our top 10 most expensive Azure resource groups?',
  'Compare GCP spend this quarter vs last quarter',
  'Break down costs by environment (dev, staging, prod)',
  'Show me daily spend trend for the last 30 days across all clouds',
  "What's our spend by business unit for Q1 2026?",
  'Show me total spend across all clouds',
  'What % of our spend is in each cloud?',
  'Which cloud has the highest storage costs?',
  'Compare compute costs: AWS EC2 vs Azure VM vs GCP Compute Engine',

  // UC-002: Trend Analysis
  'Show me month-over-month cost growth',
  'What services had the biggest cost increase this month?',
  'Project our AWS spend for next quarter based on current trends',
  'Show me week-over-week variance in compute costs',
  'Compare our spend pattern this year vs last year',

  // UC-003: Anomaly Detection
  'Did any services have unusual spend yesterday?',
  'Detect any cost spikes in the last 7 days',
  'Show me anomalies for the last week',

  // UC-004: Budget Tracking
  'How much of our Q2 budget have we spent?',
  'Are we on track to stay within budget this month?',
  'Compare actual vs budgeted spend by project',
  'Forecast if we will exceed budget this quarter',

  // UC-005: Recommendations
  'What savings opportunities exist?',
  'Show me unattached storage volumes',
  'Which EC2 instances should we rightsize?',
  'What are our Reserved Instance recommendations?',
  'Show me idle resources costing more than $100/month',
  'Show me rightsizing recommendations for Azure',

  // UC-006: Commitment Analysis
  "What's our RI coverage for EC2?",
  'Show me unutilized RIs',
  'Recommend Savings Plan purchases to maximize savings',
  'Compare RI vs Savings Plan vs On-Demand costs',

  // UC-008: Multi-Cloud
  'Show me total spend across all clouds for last month',
  'Trend of multi-cloud distribution over time',

  // UC-009: Reports
  'Generate a monthly cost report for leadership',
  "Export last quarter's spend by department to Excel",

  // UC-010: Drill-Down
  'Why did Azure spend spike last week?',
  'Show me only production resources',
  'Narrow to the top 5 most expensive services',

  // UC-011: Chargeback
  'Show me costs by team for Q1',
  'Track untagged resources',
  'Generate chargeback report',

  // Additional common queries
  'What are our top cost drivers this month?',
  'Show me GCP recommendations',
  'Compare AWS spend this month vs last month',
  'Show me Azure advisor recommendations',
  'What is our daily run rate?',
  'Show me spend by subscription',
  'Which projects have the highest cost growth?',
]

export default SUGGESTIONS
