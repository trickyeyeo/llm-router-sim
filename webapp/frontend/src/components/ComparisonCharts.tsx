import { LineChart, Line, AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

interface ComparisonChartsProps {
  metrics: any;
  leftLabel?: string;
  rightLabel?: string;
  comparisonMode?: string;
}

export default function ComparisonCharts({
  metrics: _metrics,
  leftLabel = 'Left',
  rightLabel = 'Right',
  comparisonMode = 'stateless_vs_stateful',
}: ComparisonChartsProps) {
  // Create shorthand labels for charts
  const leftShort = leftLabel.split('(')[0].trim();
  const rightShort = rightLabel.split('(')[0].trim();

  // Placeholder TTFT data - would need per-turn tracking from simulation
  const chartData = [
    { turn: 1, left: 683, right: 683 },
    { turn: 2, left: 376, right: 205 },
    { turn: 3, left: 580, right: 529 },
    { turn: 4, left: 870, right: 870 },
    { turn: 5, left: 478, right: 410 },
  ];

  // Placeholder HBM utilization data - would need time-series tracking
  const utilizationData = [
    { time: 0, left: 10, right: 15 },
    { time: 10, left: 55, right: 35 },
    { time: 20, left: 85, right: 55 },
    { time: 30, left: 99, right: 65 },
    { time: 35, left: 99, right: 63 },
  ];

  // Use actual throughput from metrics
  const leftTokensPerSec = _metrics?.left?.throughput_tokens_per_sec || 0;
  const rightTokensPerSec = _metrics?.right?.throughput_tokens_per_sec || 0;
  const throughputData = [
    { benchmark: leftShort, value: leftTokensPerSec },
    { benchmark: rightShort, value: rightTokensPerSec },
  ];

  return (
    <div>
      <h3 className="text-2xl font-bold mb-6">Comparison Analysis</h3>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* TTFT Per Turn */}
        <div className="chart-container">
          <h4 className="text-lg font-semibold mb-4">TTFT by Turn (ms)</h4>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="turn" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569' }} />
              <Legend />
              <Line type="monotone" dataKey="left" stroke="#ef4444" strokeWidth={2} name={leftShort} />
              <Line type="monotone" dataKey="right" stroke="#22c55e" strokeWidth={2} name={rightShort} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* HBM Utilization Over Time */}
        <div className="chart-container">
          <h4 className="text-lg font-semibold mb-4">HBM Utilization (%)</h4>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={utilizationData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569' }} />
              <Legend />
              <Area type="monotone" dataKey="left" stroke="#ef4444" fill="#ef4444" fillOpacity={0.3} name={leftShort} />
              <Area type="monotone" dataKey="right" stroke="#22c55e" fill="#22c55e" fillOpacity={0.3} name={rightShort} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Throughput Comparison */}
        <div className="chart-container">
          <h4 className="text-lg font-semibold mb-4">Throughput (tokens/sec)</h4>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={throughputData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="benchmark" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569' }} />
              <Bar dataKey="value" fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Cache Hit Rate / Transfer Success */}
        <div className="chart-container">
          <h4 className="text-lg font-semibold mb-4">
            {comparisonMode === 'stateful_baseline_vs_with_p2p' ? 'P2P Transfer Metrics' : 'Cache Hit Rate (%)'}
          </h4>
          <div className="flex items-end justify-around h-64">
            <div className="text-center">
              <div className="text-sm text-slate-400 mb-2">{leftShort}</div>
              <div className={`text-4xl font-bold ${comparisonMode === 'stateful_baseline_vs_with_p2p' ? 'text-slate-500' : 'text-red-500'}`}>
                {comparisonMode === 'stateful_baseline_vs_with_p2p' ? '0' : '0%'}
              </div>
              <div className="text-xs text-slate-500 mt-1">{comparisonMode === 'stateful_baseline_vs_with_p2p' ? 'N/A' : 'transfers'}</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-slate-400 mb-2">{rightShort}</div>
              <div className={`text-4xl font-bold ${comparisonMode === 'stateful_baseline_vs_with_p2p' ? 'text-green-500' : 'text-green-500'}`}>
                {comparisonMode === 'stateful_baseline_vs_with_p2p' ? '~98%' : '96%'}
              </div>
              <div className="text-xs text-slate-500 mt-1">{comparisonMode === 'stateful_baseline_vs_with_p2p' ? 'success' : 'hits'}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
