export type Kind = "text" | "email" | "decimal" | "date";
export type Rule = {
  source: string;
  target: string;
  kind: Kind;
  required: boolean;
  trim: boolean;
  collapse_spaces: boolean;
  casing: "preserve" | "lower" | "upper";
  date_format: "%Y-%m-%d" | "%m/%d/%Y" | "%d/%m/%Y";
};
export type Config = {
  fields: Rule[];
  duplicate_keys: string[];
  duplicate_policy: "keep_all" | "reject_later";
  null_markers: string[];
};
export type SourceRow = {
  row: number;
  original: Record<string, string>;
  issues: string[];
};
export type Dataset = {
  id: string;
  filename: string;
  created: string;
  columns: string[];
  notes: string[];
  row_count: number;
  rows: SourceRow[];
};
export type DatasetInfo = Omit<Dataset, "rows">;
export type AuditEvent = {
  row: number;
  field: string;
  action: string;
  before: string | null;
  after: string | null;
  reason: string;
};
export type RecordResult = {
  row: number;
  original: Record<string, string>;
  cleaned: Record<string, string | null>;
  reasons: string[];
  status: "accepted" | "rejected";
  changed: boolean;
  events: AuditEvent[];
};
export type Summary = {
  total: number;
  accepted: number;
  changed: number;
  rejected: number;
  audit_events: number;
};
export type RunInfo = {
  id: string;
  filename: string;
  created: string;
  dataset_id: string;
  summary: Summary;
};
export type RunMetadata = RunInfo & {
  config: Config;
  source_columns: string[];
  source_notes: string[];
};
export type Run = RunMetadata & {
  records: RecordResult[];
  filtered_count: number;
};
export type Filter = "all" | "accepted" | "changed" | "rejected";
