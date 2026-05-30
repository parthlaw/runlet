import ReactFlow, { Node, Edge, Background, Controls, MiniMap } from "reactflow";
import "reactflow/dist/style.css";
import { Pipeline, StepRecord } from "../api";

const STATUS_COLORS: Record<string, string> = {
  success: "#10b981",
  failed: "#ef4444",
  running: "#f59e0b",
  skipped: "#6b7280",
  pending: "#374151",
};

interface Props {
  pipeline: Pipeline;
  steps: StepRecord[];
  selectedStep: string | null;
  onSelectStep: (name: string) => void;
}

const NODE_WIDTH = 160;
const NODE_HEIGHT = 40;

function layoutNodes(pipeline: Pipeline): { nodes: Node[]; edges: Edge[] } {
  // Simple layered layout: assign each node to a column based on topological order
  const orderMap: Record<string, number> = {};
  pipeline.nodes.forEach((n) => (orderMap[n.id] = n.execution_order));

  // Group by execution_order to stack nodes in the same layer
  const layers: Record<number, string[]> = {};
  pipeline.nodes.forEach((n) => {
    const col = n.execution_order;
    (layers[col] = layers[col] ?? []).push(n.id);
  });

  const posMap: Record<string, { x: number; y: number }> = {};
  Object.entries(layers).forEach(([col, ids]) => {
    const x = Number(col) * (NODE_WIDTH + 60);
    ids.forEach((id, row) => {
      posMap[id] = { x, y: row * (NODE_HEIGHT + 20) };
    });
  });

  const nodes: Node[] = pipeline.nodes.map((n) => ({
    id: n.id,
    position: posMap[n.id] ?? { x: 0, y: 0 },
    data: { label: n.label },
    style: {
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      fontSize: 12,
      fontFamily: "monospace",
      background: "#1f2937",
      border: "1px solid #374151",
      borderRadius: 6,
      color: "#e5e7eb",
    },
  }));

  const edges: Edge[] = pipeline.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    style: { stroke: "#4b5563" },
  }));

  return { nodes, edges };
}

export function DAGView({ pipeline, steps, selectedStep, onSelectStep }: Props) {
  const statusMap: Record<string, string> = {};
  steps.forEach((s) => (statusMap[s.step_name] = s.status));

  const { nodes, edges } = layoutNodes(pipeline);

  const styledNodes = nodes.map((n) => ({
    ...n,
    style: {
      ...n.style,
      borderColor: selectedStep === n.id ? "#6366f1" : STATUS_COLORS[statusMap[n.id] ?? "pending"],
      borderWidth: selectedStep === n.id ? 2 : 1,
      cursor: "pointer",
    },
  }));

  return (
    <div style={{ height: 260 }} className="border-b border-gray-800">
      <ReactFlow
        nodes={styledNodes}
        edges={edges}
        onNodeClick={(_, node) => onSelectStep(node.id)}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnScroll
        zoomOnScroll={false}
      >
        <Background color="#1f2937" gap={16} />
        <Controls showInteractive={false} className="!bg-gray-900 !border-gray-700" />
      </ReactFlow>
    </div>
  );
}
