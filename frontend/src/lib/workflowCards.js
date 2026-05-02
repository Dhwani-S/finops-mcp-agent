/**
 * Guided workflow cards for the empty state and explore section.
 * Each workflow has an icon (SVG path), label, description, and pre-filled prompt.
 */
export const WORKFLOW_CARDS = [
  {
    id: 'cost-review',
    icon: 'bar-chart',
    label: 'Cost Review',
    description: 'See where your money goes across clouds, services, and teams',
    prompt: 'Show me a breakdown of our total spend across all clouds for last month, grouped by service',
  },
  {
    id: 'compare-clouds',
    icon: 'layers',
    label: 'Compare Clouds',
    description: 'Side-by-side comparison of AWS, Azure, and GCP spend',
    prompt: 'Compare AWS vs Azure vs GCP spend for this quarter',
  },
  {
    id: 'find-savings',
    icon: 'piggy-bank',
    label: 'Find Savings',
    description: 'Discover idle resources, rightsizing, and unattached volumes',
    prompt: 'What savings opportunities and recommendations exist across all clouds?',
  },
  {
    id: 'investigate-spike',
    icon: 'alert-triangle',
    label: 'Investigate Spike',
    description: 'Find and explain cost anomalies or sudden spend increases',
    prompt: 'Detect any cost anomalies or spikes in the last 7 days',
  },
  {
    id: 'trend-analysis',
    icon: 'trending-up',
    label: 'Trend Analysis',
    description: 'Month-over-month growth, forecasting, and variance analysis',
    prompt: 'Show me month-over-month cost growth across all clouds',
  },
  {
    id: 'budget-check',
    icon: 'gauge',
    label: 'Budget Check',
    description: 'Track spend against budget and forecast overruns',
    prompt: 'Are we on track to stay within budget this month? Show budget vs actual',
  },
]
