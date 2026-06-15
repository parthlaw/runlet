import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PipelineList } from "./components/PipelineList";
import { RunTable } from "./components/RunTable";
import { RunDetail } from "./components/RunDetail";
import { StepDrawer } from "./components/StepDrawer";
import { TopNav } from "./components/TopNav";
import { api, Pipeline, RunDetail as RunDetailType } from "./api";

function NoPipelinesState() {
  return (
    <main className="ml-60 mt-14 h-[calc(100vh-3.5rem)] overflow-hidden relative flex items-center justify-center bg-surface">
      <div
        className="absolute inset-0 pointer-events-none opacity-20"
        style={{
          backgroundImage: "radial-gradient(#464554 0.5px, transparent 0.5px)",
          backgroundSize: "24px 24px",
        }}
      />
      <div className="relative z-10 flex flex-col items-center max-w-md text-center px-gutter">
        <div className="mb-8 relative">
          <svg
            className="opacity-40"
            fill="none"
            height="120"
            viewBox="0 0 120 120"
            width="120"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <rect className="stroke-outline-variant" height="20" rx="4" strokeWidth="1.5" width="30" x="45" y="10" />
            <rect className="stroke-outline-variant" height="20" rx="4" strokeWidth="1.5" width="30" x="15" y="55" />
            <rect className="stroke-outline-variant" height="20" rx="4" strokeWidth="1.5" width="30" x="75" y="55" />
            <rect className="stroke-outline-variant" height="20" rx="4" strokeWidth="1.5" width="30" x="45" y="100" />
            <path className="stroke-outline-variant dag-outline-path" d="M60 30V45" strokeLinecap="round" strokeWidth="1.5" />
            <path className="stroke-outline-variant dag-outline-path" d="M60 45H30V55" strokeLinecap="round" strokeWidth="1.5" />
            <path className="stroke-outline-variant dag-outline-path" d="M60 45H90V55" strokeLinecap="round" strokeWidth="1.5" />
            <path className="stroke-outline-variant dag-outline-path" d="M30 75V85H60V100" strokeLinecap="round" strokeWidth="1.5" />
            <path className="stroke-outline-variant dag-outline-path" d="M90 75V85H60" strokeLinecap="round" strokeWidth="1.5" />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-12 h-12 bg-primary/5 rounded-full animate-pulse blur-xl" />
          </div>
        </div>

        <h1 className="font-display-lg text-display-lg text-on-surface mb-4">No pipelines configured</h1>
        <p className="font-body-base text-body-base text-on-surface-variant mb-8 leading-relaxed">
          Add a pipeline using the decorator API. Point Runlet at a{" "}
          <code className="font-code-sm text-code-sm bg-surface-container-highest px-1.5 py-0.5 rounded text-primary">
            pipeline.json
          </code>{" "}
          or register pipelines from Python.
        </p>

        <div className="w-full bg-surface-container-low border border-outline-variant rounded-xl p-4 text-left">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex gap-1.5">
              <div className="w-2 h-2 rounded-full bg-error/40" />
              <div className="w-2 h-2 rounded-full bg-tertiary/40" />
              <div className="w-2 h-2 rounded-full bg-success-emerald/40" />
            </div>
            <span className="text-[10px] font-label-caps text-outline uppercase tracking-widest ml-2">
              Quick Start
            </span>
          </div>
          <pre className="font-code-sm text-code-sm text-on-surface-variant leading-relaxed whitespace-pre-wrap">{`from runlet import pipeline, step

@pipeline
def my_pipeline():
    ...`}</pre>
        </div>
      </div>
    </main>
  );
}

function NoSelectionState() {
  return (
    <main className="ml-60 mt-14 h-[calc(100vh-3.5rem)] flex flex-col items-center justify-center bg-surface-container-lowest">
      <p className="font-body-sm text-body-sm text-on-surface-variant">Select a pipeline to view runs</p>
    </main>
  );
}

export default function App() {
  const [selectedPipeline, setSelectedPipeline] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedStep, setSelectedStep] = useState<string | null>(null);

  const { data: pipelines } = useQuery<Pipeline[]>({
    queryKey: ["pipelines"],
    queryFn: api.pipelines,
  });

  const { data: pipeline } = useQuery<Pipeline>({
    queryKey: ["pipeline", selectedPipeline],
    queryFn: () => api.pipeline(selectedPipeline!),
    enabled: !!selectedPipeline,
  });

  const { data: runDetail } = useQuery<RunDetailType>({
    queryKey: ["run", selectedRunId],
    queryFn: () => api.run(selectedRunId!),
    enabled: !!selectedRunId,
    refetchInterval: (query) =>
      query.state.data?.run.status === "running" ? 3_000 : false,
  });

  const activeStepRecord =
    runDetail?.steps.find((s) => s.step_name === selectedStep) ?? null;

  function handleSelectPipeline(name: string) {
    setSelectedPipeline(name);
    setSelectedRunId(null);
    setSelectedStep(null);
  }

  function handleSelectRun(runId: string) {
    setSelectedRunId(runId);
    setSelectedStep(null);
  }

  function handleCloseRun() {
    setSelectedRunId(null);
    setSelectedStep(null);
  }

  const hasPipelines = pipelines && pipelines.length > 0;

  return (
    <div className="min-h-screen bg-background overflow-hidden">
      <TopNav />

      <PipelineList selected={selectedPipeline} onSelect={handleSelectPipeline} />

      {!hasPipelines && pipelines !== undefined ? (
        <NoPipelinesState />
      ) : selectedPipeline ? (
        <>
          <RunTable
            pipeline={selectedPipeline}
            selectedRunId={selectedRunId}
            onSelect={handleSelectRun}
          />
          {selectedRunId && pipeline && (
            <RunDetail
              pipeline={pipeline}
              runId={selectedRunId}
              onClose={handleCloseRun}
              onSelectStep={setSelectedStep}
            />
          )}
          {selectedRunId && activeStepRecord && (
            <StepDrawer
              runId={selectedRunId}
              stepRecord={activeStepRecord}
              onClose={() => setSelectedStep(null)}
            />
          )}
        </>
      ) : (
        <NoSelectionState />
      )}
    </div>
  );
}
