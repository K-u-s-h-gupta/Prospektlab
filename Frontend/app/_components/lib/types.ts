/**
 * TypeScript mirror of Backend/rich_builder.py Pydantic schema
 * Ensures frontend and backend stay in sync for rich response rendering
 */

export interface Entity {
  label: string;
  ticker?: string;
  exchange?: string;
  sector?: string;
  industry?: string;
  currency?: string;
  market_cap?: number;
  current_price?: number;
  change_pct?: number;
  fifty_two_week_high?: number;
  fifty_two_week_low?: number;
  pe?: number;
  pb?: number;
  roe?: number;
  profit_margin?: number;
  operating_margin?: number;
  revenue_growth?: number;
  debt_to_equity?: number;
  dividend_yield?: number;
  description?: string;
}

export interface MetricCard {
  label: string;
  value: string;
  sub_value?: string;
  change?: string;
  change_type?: "positive" | "negative" | "neutral";
  tooltip?: string;
  icon?: string;
  entity_ref?: "primary" | "secondary";
  is_partial?: boolean;
}

export interface ChartSeries {
  name: string;
  color?: string;
  values: (number | null)[];
  unit?: string;
}

export interface Chart {
  id: string;
  kind: "bar" | "line" | "area" | "donut" | "multi_bar" | "multi_line" | "gauge";
  title: string;
  subtitle?: string;
  x_labels?: string[];
  series?: ChartSeries[];
  currency?: string;
  y_unit?: string;
  is_partial?: boolean;
}

export interface ComparisonRow {
  metric: string;
  primary_value: string;
  secondary_value: string;
  winner?: "primary" | "secondary" | "tie";
  delta?: string;
}

export interface StrengthsRisksBlock {
  entity_label: string;
  strengths?: string[];
  risks?: string[];
}

export interface NewsHeadline {
  title: string;
  url?: string;
  source?: string;
  published?: string;
  snippet?: string;
}

export interface DataSource {
  label: string;
  url?: string;
}

export interface RichResponse {
  mode: string;
  title?: string;
  subtitle?: string;
  primary_entity?: Entity;
  secondary_entity?: Entity;
  extra_entities?: Entity[];
  metric_cards?: MetricCard[];
  charts?: Chart[];
  comparison_rows?: ComparisonRow[];
  strengths_risks?: StrengthsRisksBlock[];
  headlines?: NewsHeadline[];
  valuation_summary?: Record<string, unknown>;
  filing_sections?: Array<Record<string, unknown>>;
  data_sources?: DataSource[];
  disclaimer?: string;
  markdown_body?: string;
  is_partial?: boolean;
}
