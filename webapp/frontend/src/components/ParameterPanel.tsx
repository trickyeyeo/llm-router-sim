import { useState } from 'react';

interface ParameterPanelProps {
  onRun: (params: { num_sessions: number; turns_per_session: number }) => void;
  disabled: boolean;
}

export default function ParameterPanel({ onRun, disabled }: ParameterPanelProps) {
  const [sessions, setSessions] = useState(5);
  const [turns, setTurns] = useState(5);

  const handleRun = () => {
    onRun({ num_sessions: sessions, turns_per_session: turns });
  };

  return (
    <div className="metric-card h-fit sticky top-8">
      <h2 className="text-xl font-bold mb-6">Parameters</h2>

      <div className="space-y-6">
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

        {/* Total Requests Estimate */}
        <div className="bg-slate-700/50 rounded p-3 text-sm">
          <p className="text-slate-300">
            Est. requests: <span className="font-semibold text-green-400">{sessions * turns}</span>
          </p>
          <p className="text-slate-400 text-xs mt-1">
            Running both stateless & stateful
          </p>
        </div>

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
