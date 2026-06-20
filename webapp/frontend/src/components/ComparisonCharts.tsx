import { LineChart, Line, AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

interface ComparisonChartsProps {}

export default function ComparisonCharts({}: ComparisonChartsProps) {
  // Prepare data for charts - use placeholder data for now
  const chartData = [
    { turn: 1, stateless: 683, stateful: 683 },
    { turn: 2, stateless: 376, stateful: 205 },
    { turn: 3, stateless: 580, stateful: 529 },
    { turn: 4, stateless: 870, stateful: 870 },
    { turn: 5, stateless: 478, stateful: 410 },
  ];

  const utilizationData = [
    { time: 0, stateless: 10, stateful: 15 },
    { time: 10, stateless: 55, stateful: 35 },
    { time: 20, stateless: 85, stateful: 55 },
    { time: 30, stateless: 99, stateful: 65 },
    { time: 35, stateless: 99, stateful: 63 },
  ];

  const throughputData = [
    { benchmark: 'Stateless', value: 2100 },
    { benchmark: 'Stateful', value: 2398 },
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
              <Line type="monotone" dataKey="stateless" stroke="#ef4444" strokeWidth={2} name="Stateless" />
              <Line type="monotone" dataKey="stateful" stroke="#22c55e" strokeWidth={2} name="Stateful" />
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
              <Area type="monotone" dataKey="stateless" stroke="#ef4444" fill="#ef4444" fillOpacity={0.3} name="Stateless" />
              <Area type="monotone" dataKey="stateful" stroke="#22c55e" fill="#22c55e" fillOpacity={0.3} name="Stateful" />
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

        {/* Cache Hit Rate Progression */}
        <div className="chart-container">
          <h4 className="text-lg font-semibold mb-4">Cache Hit Rate (%)</h4>
          <div className="flex items-end justify-around h-64">
            <div className="text-center">
              <div className="text-sm text-slate-400 mb-2">Stateless</div>
              <div className="text-4xl font-bold text-red-500">0%</div>
            </div>
            <div className="text-center">
              <div className="text-sm text-slate-400 mb-2">Stateful</div>
              <div className="text-4xl font-bold text-green-500">96%</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
