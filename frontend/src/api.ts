const BASE = "/api";

export interface PipelineNode {
  id: string;
  label: string;
  has_condition: boolean;
  execution_order: number;
}

export interface PipelineEdge {
  source: string;
  target: string;
}

export interface Pipeline {
  name: string;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
}

export interface RunRecord {
  run_id: string;
  pipeline_name: string;
  status: "running" | "success" | "failed" | "cancelled";
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface StepRecord {
  run_id: string;
  step_name: string;
  status: "running" | "success" | "failed" | "skipped" | "pending";
  attempt: number;
  duration_seconds: number | null;
  error: string | null;
  output: Record<string, unknown>;
  recorded_at: string;
}

export interface RunDetail {
  run: RunRecord;
  steps: StepRecord[];
}

export type FileFormat = "jsonl" | "json" | "csv" | "tsv" | "text";

export interface FileInfo {
  key: string;
  format: FileFormat;
  size_bytes: number | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  pipelines: (): Promise<Pipeline[]> => get("/pipelines"),
  pipeline: (name: string): Promise<Pipeline> => get(`/pipelines/${encodeURIComponent(name)}`),
  runs: (name: string, limit = 50): Promise<RunRecord[]> =>
    get(`/pipelines/${encodeURIComponent(name)}/runs?limit=${limit}`),
  run: (runId: string): Promise<RunDetail> => get(`/runs/${encodeURIComponent(runId)}`),
  files: (runId: string, stepName: string): Promise<FileInfo[]> =>
    get(`/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepName)}/files`),
  fileUrl: (runId: string, stepName: string, key: string): string =>
    `${BASE}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepName)}/files/${encodeURIComponent(key)}`,
};

export function isFileUri(value: unknown): value is string {
  if (typeof value !== "string") return false;
  return value.startsWith("file://") || value.startsWith("s3://") || value.startsWith("gs://");
}
