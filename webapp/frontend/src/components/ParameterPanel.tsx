import { useState } from 'react';
import DemoPresets, { DemoConfig } from './DemoPresets';
import type { SimulationParams } from '../hooks/useSimulation';

interface ParameterPanelProps {
  onRun: (params: SimulationParams) => void;
  disabled: boolean;
}

export default function ParameterPanel({ onRun, disabled }: ParameterPanelProps) {
  const [sessions, setSessions] = useState(5);
  const [turns, setTurns] = useState(5);
  const [failureRate, setFailureRate] = useState(0);
  const [networkType, setNetworkType] = useState('rdma');
  const [demoActive, setDemoActive] = useState(false);

  const handleRun = () => {
    onRun({
      num_sessions: sessions,
      turns_per_session: turns,
      failure_rate: failureRate,
      network_type: networkType,
      comparisonMode: 'stateless_vs_stateful',
    });
  };

  const handleDemoSelect = (demoConfig: DemoConfig) => {
    setSessions(demoConfig.params.num_sessions);
    setTurns(demoConfig.params.turns_per_session);
    setFailureRate(demoConfig.params.failure_rate);
    setNetworkType(demoConfig.params.network_type);
    setDemoActive(true);
    // Auto-run the demo
    setTimeout(() => {
      const simParams: SimulationParams = {
        num_sessions: demoConfig.params.num_sessions,
        turns_per_session: demoConfig.params.turns_per_session,
        failure_rate: demoConfig.params.failure_rate,
        network_type: demoConfig.params.network_type,
        comparisonMode: demoConfig.comparisonMode,
        baselineFailureRate: demoConfig.baselineParams?.failure_rate,
      };
      onRun(simParams);
    }, 200);
  };

  return (
    <div className="metric-card h-fit sticky top-8">
      <h2 className="text-xl font-bold mb-6">Configuration</h2>

      <div className="space-y-6">
        {/* Demo Presets */}
        <DemoPresets onSelectDemo={handleDemoSelect} disabled={disabled} />

        {/* Separator */}
        {demoActive && (
          <div className="border-t border-slate-600 pt-6">
            <button
              onClick={() => {
                setDemoActive(false);
                setSessions(5);
                setTurns(5);
                setFailureRate(0);
                setNetworkType('rdma');
              }}
              disabled={disabled}
              className="w-full text-sm px-3 py-2 bg-slate-700/50 hover:bg-slate-700 rounded text-slate-300 transition"
            >
              ← Back to Custom Mode
            </button>
          </div>
        )}

        {!demoActive && (
          <>
            {/* Concurrent Sessions */}
            <div>
              <label className="block text-sm font-semibold text-slate-300 mb-2">
                Concurrent Sessions: <span className="text-blue-400">{sessions}</span>
              </label>
              <input
                type="range"
                min="1"
                max="20"
                value={sessions}
                onChange={(e) => setSessions(Number(e.target.value))}
                disabled={disabled}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
              <div className="flex justify-between text-xs text-slate-500 mt-1">
                <span>1</span>
                <span>20</span>
              </div>
            </div>

            {/* Turns Per Session */}
            <div>
              <label className="block text-sm font-semibold text-slate-300 mb-2">
                Turns Per Session: <span className="text-blue-400">{turns}</span>
              </label>
              <input
                type="range"
                min="1"
                max="10"
                value={turns}
                onChange={(e) => setTurns(Number(e.target.value))}
                disabled={disabled}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
              <div className="flex justify-between text-xs text-slate-500 mt-1">
                <span>1</span>
                <span>10</span>
              </div>
            </div>

            {/* Failure Rate */}
            <div>
              <label className="block text-sm font-semibold text-slate-300 mb-2">
                Failure Rate: <span className="text-blue-400">{(failureRate * 100).toFixed(1)}%</span>
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={failureRate}
                onChange={(e) => setFailureRate(Number(e.target.value))}
                disabled={disabled}
                className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
              <div className="flex justify-between text-xs text-slate-500 mt-1">
                <span>0%</span>
                <span>100%</span>
              </div>
            </div>

            {/* Network Type */}
            <div>
              <label className="block text-sm font-semibold text-slate-300 mb-2">Network Type</label>
              <div className="grid grid-cols-2 gap-2">
                {['rdma', 'tcp'].map((type) => (
                  <button
                    key={type}
                    onClick={() => setNetworkType(type)}
                    disabled={disabled}
                    className={`px-3 py-2 rounded font-semibold uppercase text-xs transition ${
                      networkType === type
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                    } disabled:opacity-50`}
                  >
                    {type === 'rdma' ? 'RDMA (100G)' : 'TCP (10G)'}
                  </button>
                ))}
              </div>
            </div>

            {/* Total Requests Estimate */}
            <div className="bg-slate-700/50 rounded p-3 text-sm">
              <p className="text-slate-300">
                Est. requests: <span className="font-semibold text-green-400">{sessions * turns}</span>
              </p>
              <p className="text-slate-400 text-xs mt-1">Running both stateless & stateful</p>
            </div>
          </>
        )}

        {/* Run Button */}
        <button
          onClick={handleRun}
          disabled={disabled}
          className="w-full py-3 bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-500 hover:to-blue-600 disabled:from-slate-600 disabled:to-slate-700 rounded-lg font-bold transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {disabled ? '⟳ Running...' : '▶ Run Simulation'}
        </button>
      </div>
    </div>
  );
}
