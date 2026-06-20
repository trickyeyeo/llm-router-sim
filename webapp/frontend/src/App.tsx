import { useState } from 'react';
import ParameterPanel from './components/ParameterPanel';
import ProgressIndicator from './components/ProgressIndicator';
import GPUCards from './components/GPUCards';
import KeyMetrics from './components/KeyMetrics';
import ComparisonCharts from './components/ComparisonCharts';
import ExpertAccordion from './components/ExpertAccordion';
import { useSimulation, type SimulationParams } from './hooks/useSimulation';
import { downloadPDF } from './utils/pdfExport';

export default function App() {
  const [params, setParams] = useState<SimulationParams>({
    num_sessions: 5,
    turns_per_session: 5,
    failure_rate: 0,
    network_type: 'rdma',
    comparisonMode: 'stateless_vs_stateful',
  });

  const [shouldRun, setShouldRun] = useState(false);
  const { simState, running } = useSimulation(params, shouldRun);

  const handleRun = (newParams: SimulationParams) => {
    setParams(newParams);
    setShouldRun(true);
  };

  const handleExportPDF = async () => {
    await downloadPDF(simState);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-800 text-white">
      {/* Header */}
      <div className="bg-slate-800/50 border-b border-slate-700 px-8 py-6">
        <h1 className="text-4xl font-bold mb-2">Multi-turn Agent Router Demo</h1>
        <p className="text-slate-400">
          Comparing stateless vs prefix-aware routing for agentic workloads
        </p>
      </div>

      <div className="max-w-7xl mx-auto px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
          {/* Left Sidebar */}
          <div className="lg:col-span-1">
            <ParameterPanel onRun={handleRun} disabled={running} />
          </div>

          {/* Main Content */}
          <div className="lg:col-span-3 space-y-8">
            {/* Progress Indicator */}
            {running && (
              <ProgressIndicator
                progress={simState.progress}
                currentTime={simState.current_time_ms}
                totalTime={simState.total_time_ms}
                requestsStateless={simState.left?.requests}
                requestsStateful={simState.right?.requests}
              />
            )}

            {/* GPU Cards */}
            {(running || simState.final_metrics) && (
              <GPUCards
                stateless={simState.left?.gpus}
                stateful={simState.right?.gpus}
                leftLabel={simState.left?.label}
                rightLabel={simState.right?.label}
                comparisonMode={simState.comparisonMode}
              />
            )}

            {/* Key Metrics */}
            {simState.final_metrics && (
              <KeyMetrics
                metrics={simState.final_metrics}
                leftLabel={simState.left?.label}
                rightLabel={simState.right?.label}
                comparisonMode={simState.comparisonMode}
              />
            )}

            {/* Comparison Charts */}
            {simState.final_metrics && (
              <ComparisonCharts
                metrics={simState.final_metrics}
                leftLabel={simState.left?.label}
                rightLabel={simState.right?.label}
                comparisonMode={simState.comparisonMode}
              />
            )}

            {/* Expert Accordion */}
            {simState.final_metrics && (
              <>
                <ExpertAccordion
                  metrics={simState.final_metrics}
                  leftLabel={simState.left?.label}
                  rightLabel={simState.right?.label}
                  comparisonMode={simState.comparisonMode}
                />

                {/* PDF Export Button */}
                <div className="flex justify-end pt-4">
                  <button
                    onClick={handleExportPDF}
                    className="px-6 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg font-semibold transition"
                  >
                    📥 Download Results as PDF
                  </button>
                </div>
              </>
            )}

            {/* Empty State */}
            {!running && !simState.final_metrics && (
              <div className="text-center py-16 text-slate-400">
                <p className="text-lg">
                  Adjust parameters on the left and click "Run Simulation" to begin
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
