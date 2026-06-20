import { useState } from 'react';

export interface DemoConfig {
  name: string;
  description: string;
  expectedResults: string;
  whyItMatters: string;
  comparisonMode: 'stateless_vs_stateful' | 'stateful_baseline_vs_with_p2p';
  params: {
    num_sessions: number;
    turns_per_session: number;
    failure_rate: number;
    network_type: string;
  };
  baselineParams?: {
    failure_rate: number;
  };
}

const DEMO_PRESETS: DemoConfig[] = [
  {
    name: 'Caching Affinity',
    description: 'Shows how scoring-based routing promotes cache hits and reuse for capacity improvement',
    comparisonMode: 'stateless_vs_stateful',
    expectedResults: 'Stateful: ~99% cache hit rate, all 115 blocks on GPU0 (cache concentration). Stateless: ~0% hits, ~92 blocks on each GPU (balanced). TTFT: stateful 282ms vs stateless 396ms (29% faster). Throughput: ~2.0 req/sec both (same #requests in 35s, cache saves latency not end-to-end time). Key: cache concentration is the routing feature.',
    whyItMatters: 'Demonstrates prefix-affinity routing: routes to cache owner rather than spreading load randomly, concentrating cache for maximum reuse efficiency.',
    params: {
      num_sessions: 50,
      turns_per_session: 3,
      failure_rate: 0,
      network_type: 'rdma',
    },
  },
  {
    name: 'Graceful Degradation',
    description: 'System recovers from GPU failures via P2P KV cache transfers, minimizing latency impact',
    comparisonMode: 'stateful_baseline_vs_with_p2p',
    expectedResults: 'Baseline (20% failures, no P2P): 40 requests at 1.14 req/sec, avg TTFT 177ms, p99 TTFT 341ms. With P2P recovery: 40 requests at 1.14 req/sec, avg TTFT 177ms, p99 TTFT 341ms. Note: P2P recovery feature is under development (transfers not yet initiated on failures).',
    whyItMatters: 'Demonstrates resilience strategy: when GPU fails, requests route to healthy instances. Full P2P recovery (transferring KV blocks via RDMA to avoid re-prefilling from scratch) will minimize latency impact vs cascading failures.',
    params: {
      num_sessions: 20,
      turns_per_session: 2,
      failure_rate: 0.2,
      network_type: 'rdma',
    },
    baselineParams: {
      failure_rate: 0.2,
    },
  },
];

interface DemoPresetsProps {
  onSelectDemo: (demoConfig: DemoConfig) => void;
  disabled?: boolean;
}

export default function DemoPresets({ onSelectDemo, disabled }: DemoPresetsProps) {
  const [selectedDemo, setSelectedDemo] = useState<string | null>(null);

  const handleSelectDemo = (demoConfig: DemoConfig) => {
    setSelectedDemo(demoConfig.name);
    onSelectDemo(demoConfig);
  };

  const activeDemoConfig = selectedDemo
    ? DEMO_PRESETS.find((d) => d.name === selectedDemo)
    : null;

  return (
    <div className="space-y-6">
      {/* Demo Buttons */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
          Pre-Canned Demos
        </h3>
        <div className="space-y-2">
          {DEMO_PRESETS.map((demo) => (
            <button
              key={demo.name}
              onClick={() => handleSelectDemo(demo)}
              disabled={disabled}
              className={`w-full px-4 py-3 rounded-lg text-left transition-all ${
                selectedDemo === demo.name
                  ? 'bg-blue-600 border border-blue-400 shadow-lg'
                  : 'bg-slate-700 border border-slate-600 hover:bg-slate-600 hover:border-slate-500'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              <div className="font-medium text-sm">{demo.name}</div>
              <div className="text-xs text-slate-300 mt-1">{demo.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Demo Details */}
      {activeDemoConfig && (
        <div className="bg-slate-700/50 border border-slate-600 rounded-lg p-4 space-y-3">
          <div>
            <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Expected Results
            </h4>
            <p className="text-sm text-slate-200">{activeDemoConfig.expectedResults}</p>
          </div>

          <div className="border-t border-slate-600 pt-3">
            <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Why It Matters
            </h4>
            <p className="text-sm text-slate-300">{activeDemoConfig.whyItMatters}</p>
          </div>

          <div className="bg-slate-800/50 rounded p-3 space-y-2 text-xs">
            <div>
              <span className="text-slate-400">Sessions:</span>
              <span className="text-slate-200 ml-2 font-mono">{activeDemoConfig.params.num_sessions}</span>
            </div>
            <div>
              <span className="text-slate-400">Turns/Session:</span>
              <span className="text-slate-200 ml-2 font-mono">{activeDemoConfig.params.turns_per_session}</span>
            </div>
            <div>
              <span className="text-slate-400">Failure Rate:</span>
              <span className="text-slate-200 ml-2 font-mono">{activeDemoConfig.params.failure_rate * 100}%</span>
            </div>
            <div>
              <span className="text-slate-400">Network:</span>
              <span className="text-slate-200 ml-2 font-mono uppercase">{activeDemoConfig.params.network_type}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
