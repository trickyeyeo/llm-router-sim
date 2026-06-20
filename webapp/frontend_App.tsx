import React, { useState, useEffect } from 'react';
import ParameterPanel from './components/ParameterPanel';
import ProgressIndicator from './components/ProgressIndicator';
import GPUCards from './components/GPUCards';
import KeyMetrics from './components/KeyMetrics';
import ComparisonCharts from './components/ComparisonCharts';
import ExpertAccordion from './components/ExpertAccordion';
import { useSimulation } from './hooks/useSimulation';
import { downloadPDF } from './utils/pdfExport';

export default function App() {
  const [params, setParams] = useState({
    num_sessions: 5,
    turns_per_session: 5,
  });

  const [shouldRun, setShouldRun] = useState(false);
  const { simState, running } = useSimulation(params, shouldRun);

  const handleRun = (newParams: typeof params) => {
    setParams(newParams);
    setShouldRun(true);
  };

  const handleExportPDF = () => {
    downloadPDF(simState);
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
        {/* Controls */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 mb-8">
          <div className="lg:col-span-1">
            <ParameterPanel onRun={handleRun} disabled={running} />
          </div>

          {/* Main Content */}
          <div className="lg:col-span-3 space-y-8">
            {/* Progress */}
            {running && (
              <ProgressIndicator
                progress={simState.progress}
                currentTime={simState.current_time_ms}
                totalTime={simState.total_time_ms}
                requestsStateless={simState.stateless?.requests}
                requestsStateful={simState.stateful?.requests}
              />
            )}

            {/* GPU Cards */}
            {(running || simState.final_metrics) && (
              <GPUCards
                stateless={simState.stateless?.gpus}
                stateful={simState.stateful?.gpus}
              />
            )}

            {/* Key Metrics */}
            {simState.final_metrics && (
              <KeyMetrics metrics={simState.final_metrics} />
            )}

            {/* Comparison Charts */}
            {simState.final_metrics && (
              <ComparisonCharts metrics={simState.final_metrics} />
            )}

            {/* Expert Accordion */}
            {simState.final_metrics && (
              <>
                <ExpertAccordion metrics={simState.final_metrics} />

                {/* Export Button */}
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

            {/* No Results State */}
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
