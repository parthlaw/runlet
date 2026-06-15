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

const STATUS_COLOR: Record<string, string> = {
  success: "#10b981",
  failed:  "#ef4444",
  running: "#f59e0b",
  skipped: "#4b5563",
  pending: "#292932",
};

const STATUS_ICON: Record<string, React.ReactNode> = {
  success: <CheckCircle2 className="w-3 h-3 text-status-success shrink-0" />,
  failed:  <XCircle      className="w-3 h-3 text-status-failed shrink-0" />,
  running: <Loader2      className="w-3 h-3 text-status-running shrink-0 animate-spin" />,
  skipped: <MinusCircle  className="w-3 h-3 text-content-ghost shrink-0" />,
  pending: <Clock        className="w-3 h-3 text-surface-highest shrink-0" />,
};

const STATUS_TEXT: Record<string, string> = {
  success: "text-status-success",
  failed:  "text-status-failed",
  running: "text-status-running",
  skipped: "text-content-ghost",
  pending: "text-surface-highest",
};

// ---------------------------------------------------------------------------
// Custom node — left-side color strip design
// ---------------------------------------------------------------------------

function StepNode({ data }: NodeProps) {
  const { label, status, duration, selected: isSelected } = data as {
    label: string;
    status: Status;
    duration: number | null;
    selected: boolean;
  };

  const stripColor = STATUS_COLOR[status] ?? STATUS_COLOR.pending;
  const animClass =
    status === "running" ? "step-node-running" :
    status === "failed"  ? "step-node-failed"  : "";

  return (
    <>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div
        className={`relative flex items-stretch overflow-hidden select-none ${animClass}`}
        style={{
          width: 186,
          background: "#1b1b23",
          border: isSelected
            ? "1px solid #6366f1"
            : "1px solid #464554",
          borderRadius: 4,
          boxShadow: isSelected ? "0 0 0 3px rgba(99,102,241,0.2)" : undefined,
          transition: "border-color 0.15s, box-shadow 0.15s",
        }}
      >
        {/* Left color strip */}
        <div
          style={{
            width: 4,
            flexShrink: 0,
            background: isSelected ? "#6366f1" : stripColor,
            transition: "background 0.15s",
          }}
        />

        {/* Content */}
        <div className="flex flex-col gap-1 px-2.5 py-2 flex-1 min-w-0">
          <span
            className="font-mono text-xs font-semibold text-content truncate leading-tight"
            title={label}
          >
            {label}
          </span>
          <div className="flex items-center gap-1.5">
            {STATUS_ICON[status]}
            <span className={`font-mono text-[10px] ${STATUS_TEXT[status]}`}>{status}</span>
            {duration != null && (
              <span className="ml-auto font-mono text-[10px] text-content-ghost shrink-0">
                {duration.toFixed(1)}s
              </span>
            )}
          </div>
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

const NODE_W = 186;
const NODE_H = 56;
const COL_GAP = 72;
const ROW_GAP = 20;

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
    const isPending = srcStatus === "pending";
    return {
      id: `e${i}`,
      source: e.source,
      target: e.target,
      type: "smoothstep",
      style: {
        stroke: STATUS_COLOR[srcStatus] ?? STATUS_COLOR.pending,
        strokeWidth: 1,
        opacity: isPending ? 0.2 : 0.6,
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
    <div style={{ height: 280 }} className="border-b border-outline-strong">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelectStep(node.id)}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnScroll
        zoomOnScroll={false}
        minZoom={0.3}
        maxZoom={2}
      >
        <Background color="#1f1f27" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
