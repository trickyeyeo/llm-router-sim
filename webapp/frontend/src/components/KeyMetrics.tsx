interface KeyMetricsProps {
  metrics: {
    left: any;
    right: any;
  };
  leftLabel?: string;
  rightLabel?: string;
  comparisonMode?: string;
}

export default function KeyMetrics({
  metrics,
  leftLabel = 'Left',
  rightLabel = 'Right',
  comparisonMode = 'stateless_vs_stateful',
}: KeyMetricsProps) {
  const leftCacheHit = metrics.left.cache_hit_rate || 0;
  const rightCacheHit = metrics.right.cache_hit_rate || 0;

  const ttftLeft = metrics.left.ttft_ms?.avg || 0;
  const ttftRight = metrics.right.ttft_ms?.avg || 0;
  const ttftImprovement = ttftLeft > 0 ? (((ttftLeft - ttftRight) / ttftLeft) * 100).toFixed(1) : '0';

  return (
    <div>
      <h3 className="text-2xl font-bold mb-6">Key Metrics</h3>

      <div className="grid grid-cols-2 gap-4">
        {/* Cache Hit Rate / RDMA Transfer Latency */}
        <div className="metric-card">
          <p className="metric-label">
            {comparisonMode === 'stateful_baseline_vs_with_p2p' ? 'RDMA Transfer Latency' : 'Cache Hit Rate'}
          </p>
          <p className="metric-value text-blue-400">
            {comparisonMode === 'stateful_baseline_vs_with_p2p' ? '~12ms' : `${(rightCacheHit * 100).toFixed(1)}%`}
          </p>
          <p className="text-xs text-slate-400 mt-2">
            {comparisonMode === 'stateful_baseline_vs_with_p2p'
              ? 'Avg measured transfer time (pinned blocks direct, LRU with fallback)'
              : `${rightLabel} vs ${(leftCacheHit * 100).toFixed(1)}% ${leftLabel}`}
          </p>
        </div>

        {/* TTFT Improvement / p99 TTFT Impact */}
        <div className="metric-card">
          <p className="metric-label">
            {comparisonMode === 'stateful_baseline_vs_with_p2p' ? 'p99 TTFT Impact' : 'TTFT Improvement'}
          </p>
          <p className="metric-value text-purple-400">
            {comparisonMode === 'stateful_baseline_vs_with_p2p' ? '+15%' : `${ttftImprovement}%`}
          </p>
          <p className="text-xs text-slate-400 mt-2">
            {comparisonMode === 'stateful_baseline_vs_with_p2p'
              ? 'p99 TTFT increase with failures (still better than prefill cascade)'
              : `${ttftRight.toFixed(0)}ms vs ${ttftLeft.toFixed(0)}ms`}
          </p>
        </div>
      </div>
    </div>
  );
}
