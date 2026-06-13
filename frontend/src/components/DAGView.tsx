import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  NodeProps,
  Handle,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";
import { CheckCircle2, XCircle, Loader2, MinusCircle, Clock } from "lucide-react";
import type { Pipeline, StepRecord } from "../api";

// ---------------------------------------------------------------------------
// Status palette
// ---------------------------------------------------------------------------

type Status = "success" | "failed" | "running" | "skipped" | "pending";

const STATUS_BORDER: Record<string, string> = {
  success: "#10b981",
  failed:  "#ef4444",
  running: "#f59e0b",
  skipped: "#4b5563",
  pending: "#1f2937",
};

const STATUS_ICON: Record<string, React.ReactNode> = {
  success: <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />,
  failed:  <XCircle      className="w-3 h-3 text-red-400 shrink-0" />,
  running: <Loader2      className="w-3 h-3 text-amber-400 shrink-0 animate-spin" />,
  skipped: <MinusCircle  className="w-3 h-3 text-gray-500 shrink-0" />,
  pending: <Clock        className="w-3 h-3 text-gray-700 shrink-0" />,
};

const STATUS_LABEL: Record<string, string> = {
  success: "text-emerald-400",
  failed:  "text-red-400",
  running: "text-amber-400",
  skipped: "text-gray-500",
  pending: "text-gray-700",
};

// ---------------------------------------------------------------------------
// Custom node
// ---------------------------------------------------------------------------

function StepNode({ id, data }: NodeProps) {
  const { label, status, duration, selected: isSelected } = data as {
    label: string;
    status: Status;
    duration: number | null;
    selected: boolean;
  };

  const borderColor = isSelected ? "#6366f1" : STATUS_BORDER[status] ?? STATUS_BORDER.pending;
  const animClass =
    status === "running" ? "step-node-running" :
    status === "failed"  ? "step-node-failed"  : "";

  return (
    <>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div
        className={`flex flex-col gap-1 px-3 py-2.5 rounded-xl bg-gray-900 text-xs font-mono select-none ${animClass}`}
        style={{
          width: 180,
          border: `2px solid ${borderColor}`,
          boxShadow: isSelected ? `0 0 0 3px rgba(99,102,241,0.25)` : undefined,
          transition: "border-color 0.2s, box-shadow 0.2s",
        }}
      >
        <span className="font-semibold text-gray-100 truncate leading-tight">{label}</span>
        <div className="flex items-center gap-1.5">
          {STATUS_ICON[status]}
          <span className={`${STATUS_LABEL[status]} text-[10px]`}>{status}</span>
          {duration != null && (
            <span className="ml-auto text-gray-600 text-[10px] shrink-0">
              {duration.toFixed(1)}s
            </span>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </>
  );
}

const nodeTypes = { step: StepNode };

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

const NODE_W = 180;
const NODE_H = 58;
const COL_GAP = 80;
const ROW_GAP = 24;

function buildLayout(
  pipeline: Pipeline,
  statusMap: Record<string, string>,
  durationMap: Record<string, number | null>,
  selectedStep: string | null
): { nodes: Node[]; edges: Edge[] } {
  const layers: Record<number, string[]> = {};
  pipeline.nodes.forEach((n) => {
    (layers[n.execution_order] = layers[n.execution_order] ?? []).push(n.id);
  });

  const posMap: Record<string, { x: number; y: number }> = {};
  Object.entries(layers).forEach(([col, ids]) => {
    const x = Number(col) * (NODE_W + COL_GAP);
    const totalH = ids.length * NODE_H + (ids.length - 1) * ROW_GAP;
    ids.forEach((id, row) => {
      posMap[id] = { x, y: row * (NODE_H + ROW_GAP) - totalH / 2 + 100 };
    });
  });

  const nodes: Node[] = pipeline.nodes.map((n) => {
    const status = (statusMap[n.id] ?? "pending") as Status;
    return {
      id: n.id,
      type: "step",
      position: posMap[n.id] ?? { x: 0, y: 0 },
      data: {
        label: n.label,
        status,
        duration: durationMap[n.id] ?? null,
        selected: selectedStep === n.id,
      },
    };
  });

  const edges: Edge[] = pipeline.edges.map((e, i) => {
    const srcStatus = statusMap[e.source] ?? "pending";
    return {
      id: `e${i}`,
      source: e.source,
      target: e.target,
      type: "smoothstep",
      style: {
        stroke: STATUS_BORDER[srcStatus] ?? STATUS_BORDER.pending,
        strokeWidth: 1.5,
        opacity: srcStatus === "pending" ? 0.3 : 0.7,
      },
      animated: srcStatus === "running",
    };
  });

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// DAGView
// ---------------------------------------------------------------------------

interface Props {
  pipeline: Pipeline;
  steps: StepRecord[];
  selectedStep: string | null;
  onSelectStep: (name: string) => void;
}

export function DAGView({ pipeline, steps, selectedStep, onSelectStep }: Props) {
  const statusMap: Record<string, string> = {};
  const durationMap: Record<string, number | null> = {};
  steps.forEach((s) => {
    statusMap[s.step_name] = s.status;
    durationMap[s.step_name] = s.duration_seconds;
  });

  const { nodes, edges } = buildLayout(pipeline, statusMap, durationMap, selectedStep);

  return (
    <div style={{ height: 288 }} className="border-b border-gray-800">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelectStep(node.id)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnScroll
        zoomOnScroll={false}
        minZoom={0.3}
        maxZoom={2}
      >
        <Background color="#1f2937" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
