interface KeyMetricsProps {
  metrics: {
    stateless: any;
    stateful: any;
  };
}

export default function KeyMetrics({ metrics }: KeyMetricsProps) {
  const statelessCompleted = metrics.stateless.completed_requests || 0;
  const statefulCompleted = metrics.stateful.completed_requests || 0;
  const capacityImprovement = statelessCompleted > 0 ? (statefulCompleted / statelessCompleted).toFixed(2) : '—';

  const statelessCacheHit = metrics.stateless.cache_hit_rate || 0;
  const statefulCacheHit = metrics.stateful.cache_hit_rate || 0;
  const costReduction = ((1 - statefulCacheHit) * 100).toFixed(1);

  const ttftStateless = metrics.stateless.ttft_ms?.avg || 0;
  const ttftStateful = metrics.stateful.ttft_ms?.avg || 0;
  const ttftImprovement = ttftStateless > 0 ? (((ttftStateless - ttftStateful) / ttftStateless) * 100).toFixed(1) : '0';

  return (
    <div>
      <h3 className="text-2xl font-bold mb-6">Key Metrics</h3>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Capacity Improvement */}
        <div className="metric-card">
          <p className="metric-label">Capacity Increase</p>
          <p className="metric-value text-green-400">{capacityImprovement}x</p>
          <p className="text-xs text-slate-400 mt-2">More customers on same hardware</p>
        </div>

        {/* Cache Hit Rate */}
        <div className="metric-card">
          <p className="metric-label">Cache Hit Rate</p>
          <p className="metric-value text-blue-400">{(statefulCacheHit * 100).toFixed(1)}%</p>
          <p className="text-xs text-slate-400 mt-2">Stateful vs {(statelessCacheHit * 100).toFixed(1)}% stateless</p>
        </div>

        {/* Cost Reduction */}
        <div className="metric-card">
          <p className="metric-label">Cost Reduction</p>
          <p className="metric-value text-yellow-400">~{costReduction}%</p>
          <p className="text-xs text-slate-400 mt-2">From reduced prefill compute</p>
        </div>

        {/* TTFT Improvement */}
        <div className="metric-card">
          <p className="metric-label">TTFT Improvement</p>
          <p className="metric-value text-purple-400">{ttftImprovement}%</p>
          <p className="text-xs text-slate-400 mt-2">{ttftStateful.toFixed(0)}ms vs {ttftStateless.toFixed(0)}ms</p>
        </div>
      </div>
    </div>
  );
}
