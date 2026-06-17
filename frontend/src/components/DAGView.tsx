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

type Status = "success" | "failed" | "running" | "skipped" | "pending";

const STATUS_COLOR: Record<string, string> = {
  success: "#10b981",
  failed: "#ffb4ab",
  running: "#d97721",
  skipped: "#908fa0",
  pending: "#464554",
};

const STATUS_ICON: Record<string, React.ReactNode> = {
  success: <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />,
  failed: <XCircle className="w-3 h-3 text-error shrink-0" />,
  running: <Loader2 className="w-3 h-3 text-tertiary-container shrink-0 animate-spin" />,
  skipped: <MinusCircle className="w-3 h-3 text-outline shrink-0" />,
  pending: <Clock className="w-3 h-3 text-outline shrink-0" />,
};

const STATUS_TEXT: Record<string, string> = {
  success: "text-emerald-400",
  failed: "text-error",
  running: "text-tertiary-container",
  skipped: "text-on-surface-variant",
  pending: "text-on-surface-variant",
};

function StepNode({ data }: NodeProps) {
  const { label, status, duration, selected: isSelected, compact } = data as {
    label: string;
    status: Status;
    duration: number | null;
    selected: boolean;
    compact?: boolean;
  };

  const stripColor = STATUS_COLOR[status] ?? STATUS_COLOR.pending;
  const animClass =
    status === "running" ? "step-node-running" :
    status === "failed" ? "step-node-failed" : "";

  const width = compact ? 140 : 186;

  return (
    <>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div
        className={`relative flex items-stretch overflow-hidden select-none ${animClass}`}
        style={{
          width,
          background: compact ? "#13131b" : "#13131b",
          border: isSelected ? "1px solid #c0c1ff" : "1px solid #464554",
          borderRadius: 2,
          boxShadow: isSelected ? "0 0 0 3px rgba(192,193,255,0.2)" : undefined,
          transition: "border-color 0.2s, box-shadow 0.2s",
        }}
      >
        <div
          style={{
            width: 4,
            flexShrink: 0,
            background: isSelected ? "#c0c1ff" : stripColor,
            transition: "background 0.2s",
          }}
        />
        <div className="flex flex-col gap-1 px-2 py-1.5 flex-1 min-w-0">
          <span
            className="font-code-sm text-code-sm font-semibold text-on-surface truncate leading-tight"
            title={label}
          >
            {label}
          </span>
          <div className="flex items-center gap-1.5">
            {STATUS_ICON[status]}
            <span className={`font-code-sm text-code-sm ${STATUS_TEXT[status]}`}>{status}</span>
            {duration != null && (
              <span className="ml-auto font-code-sm text-code-sm text-on-surface-variant shrink-0">
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

const NODE_W_FULL = 186;
const NODE_W_COMPACT = 140;
const NODE_H = 56;
const COL_GAP = 72;
const ROW_GAP = 20;

function buildLayout(
  pipeline: Pipeline,
  statusMap: Record<string, string>,
  durationMap: Record<string, number | null>,
  selectedStep: string | null,
  compact: boolean
): { nodes: Node[]; edges: Edge[] } {
  const nodeW = compact ? NODE_W_COMPACT : NODE_W_FULL;
  const layers: Record<number, string[]> = {};
  pipeline.nodes.forEach((n) => {
    (layers[n.execution_order] = layers[n.execution_order] ?? []).push(n.id);
  });

  const posMap: Record<string, { x: number; y: number }> = {};
  Object.entries(layers).forEach(([col, ids]) => {
    const x = Number(col) * (nodeW + (compact ? 40 : COL_GAP));
    const totalH = ids.length * NODE_H + (ids.length - 1) * ROW_GAP;
    ids.forEach((id, row) => {
      posMap[id] = { x, y: row * (NODE_H + ROW_GAP) - totalH / 2 + (compact ? 60 : 100) };
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
        compact,
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

interface Props {
  pipeline: Pipeline;
  steps: StepRecord[];
  selectedStep: string | null;
  onSelectStep: (name: string) => void;
  compact?: boolean;
  fillHeight?: boolean;
}

export function DAGView({
  pipeline,
  steps,
  selectedStep,
  onSelectStep,
  compact = false,
  fillHeight = false,
}: Props) {
  const statusMap: Record<string, string> = {};
  const durationMap: Record<string, number | null> = {};
  steps.forEach((s) => {
    statusMap[s.step_name] = s.status;
    durationMap[s.step_name] = s.duration_seconds;
  });

  const { nodes, edges } = buildLayout(
    pipeline,
    statusMap,
    durationMap,
    selectedStep,
    compact
  );

  const fixedHeight = compact ? 200 : fillHeight ? undefined : 280;

  return (
    <div
      style={fixedHeight != null ? { height: fixedHeight } : undefined}
      className={
        fillHeight
          ? "absolute inset-0 bg-[#0d0d15] overflow-hidden"
          : compact
            ? "relative w-full aspect-video bg-black rounded-xl border border-outline-variant overflow-hidden"
            : "border-b border-outline-variant"
      }
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelectStep(node.id)}
        fitView
        fitViewOptions={{ padding: compact ? 0.15 : fillHeight ? 0.2 : 0.25 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnScroll
        zoomOnScroll={fillHeight}
        minZoom={0.2}
        maxZoom={2}
      >
        <Background color={compact || fillHeight ? "#0d0d15" : "#1f1f27"} gap={20} size={1} />
        {(fillHeight || !compact) && <Controls showInteractive={false} />}
      </ReactFlow>
    </div>
  );
}
