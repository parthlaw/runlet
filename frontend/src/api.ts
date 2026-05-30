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
  paths: Record<string, { uri: string; schema_name: string; schema_version: number }>;
  schema_info: Record<string, unknown>;
  recorded_at: string;
}

export interface RunDetail {
  run: RunRecord;
  steps: StepRecord[];
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
  artifactsUrl: (runId: string, step: string, output = "") =>
    `${BASE}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(step)}/artifacts${output ? `?output=${encodeURIComponent(output)}` : ""}`,
};

export async function fetchArtifacts(runId: string, step: string): Promise<Record<string, unknown>[]> {
  const url = api.artifactsUrl(runId, step);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const text = await res.text();
  return text
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}
