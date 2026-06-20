import { useState } from 'react';

export interface DemoConfig {
  name: string;
  description: string;
  expectedResults: string;
  whyItMatters: string;
  comparisonMode: 'stateless_vs_stateful' | 'stateful_baseline_vs_with_p2p' | 'stateful_rdma_vs_tcp';
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
    name: 'Thundering Herd Prevention',
    description: 'Shows how scoring-based routing prevents all requests from queuing on one GPU',
    comparisonMode: 'stateless_vs_stateful',
    expectedResults: 'Stateful: 85-95% cache hit rate, balanced queue depth. Stateless: 0% cache hits, heavy queue on random GPU.',
    whyItMatters: 'Demonstrates capacity improvement: stateful routing distributes load intelligently while maintaining cache reuse.',
    params: {
      num_sessions: 50,
      turns_per_session: 3,
      failure_rate: 0,
      network_type: 'rdma',
    },
  },
  {
    name: 'Graceful Degradation',
    description: 'System continues serving requests despite GPU failures and recovers via P2P transfers',
    comparisonMode: 'stateful_baseline_vs_with_p2p',
    expectedResults: 'Baseline (no failures): 85-95% cache hit. With 20% failures: latency spike, then recovery via P2P transfers.',
    whyItMatters: 'Proves resilience story: even with failures, system recovers automatically with P2P KV cache transfers.',
    params: {
      num_sessions: 20,
      turns_per_session: 2,
      failure_rate: 0.2,
      network_type: 'rdma',
    },
    baselineParams: {
      failure_rate: 0,
    },
  },
  {
    name: 'RDMA vs TCP Network',
    description: 'Compare P2P transfer performance: high-speed RDMA vs standard TCP',
    comparisonMode: 'stateful_rdma_vs_tcp',
    expectedResults: 'RDMA: Transfers in ~10-15ms. TCP: Transfers in ~100-150ms. Gap: 15-25% latency improvement with RDMA.',
    whyItMatters: 'Shows why RDMA matters: 10x faster transfers mean failures have minimal impact on customer latency.',
    params: {
      num_sessions: 5,
      turns_per_session: 3,
      failure_rate: 0.05,
      network_type: 'rdma',
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
              <span className="text-slate-200 ml-2 font-mono">{activeDemoConfig.num_sessions}</span>
            </div>
            <div>
              <span className="text-slate-400">Turns/Session:</span>
              <span className="text-slate-200 ml-2 font-mono">{activeDemoConfig.turns_per_session}</span>
            </div>
            <div>
              <span className="text-slate-400">Failure Rate:</span>
              <span className="text-slate-200 ml-2 font-mono">{(activeDemoConfig.failure_rate || 0) * 100}%</span>
            </div>
            <div>
              <span className="text-slate-400">Network:</span>
              <span className="text-slate-200 ml-2 font-mono uppercase">{activeDemoConfig.network_type}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
