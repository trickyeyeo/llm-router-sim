interface GPUState {
  gpu0?: {
    hbm_utilization: number;
    cache_hit_rate: number;
    num_cached_blocks: number;
    active_requests: number;
  };
  gpu1?: {
    hbm_utilization: number;
    cache_hit_rate: number;
    num_cached_blocks: number;
    active_requests: number;
  };
}

interface GPUCardsProps {
  stateless?: GPUState;
  stateful?: GPUState;
}

function getUtilizationColor(util: number): string {
  if (util < 0.5) return 'green';
  if (util < 0.8) return 'yellow';
  return 'red';
}

function GPUCard({
  gpuId,
  hbmUtil,
  cacheHitRate,
  blocks,
  activeRequests,
  color,
}: {
  gpuId: string;
  hbmUtil: number;
  cacheHitRate: number;
  blocks: number;
  activeRequests: number;
  color: string;
}) {
  const borderColor = color === 'green' ? 'border-green-600/50' : color === 'yellow' ? 'border-yellow-600/50' : 'border-red-600/50';
  const textColor = color === 'green' ? 'text-green-400' : color === 'yellow' ? 'text-yellow-400' : 'text-red-400';

  return (
    <div className={`gpu-card ${borderColor}`}>
      <h4 className="font-semibold mb-3">{gpuId}</h4>
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-slate-400">HBM:</span>
          <span className={textColor}>{(hbmUtil * 100).toFixed(1)}%</span>
        </div>
        <div className="w-full h-1 bg-slate-700 rounded overflow-hidden">
          <div
            className={`h-full transition-all duration-300 ${
              color === 'green' ? 'bg-green-500' : color === 'yellow' ? 'bg-yellow-500' : 'bg-red-500'
            }`}
            style={{ width: `${hbmUtil * 100}%` }}
          ></div>
        </div>

        <div className="flex justify-between mt-3">
          <span className="text-slate-400">Cache Hit:</span>
          <span className="text-blue-400">{(cacheHitRate * 100).toFixed(1)}%</span>
        </div>

        <div className="flex justify-between">
          <span className="text-slate-400">Blocks:</span>
          <span className="text-slate-300">{blocks}</span>
        </div>

        <div className="flex justify-between">
          <span className="text-slate-400">Active:</span>
          <span className="text-slate-300">{activeRequests}</span>
        </div>
      </div>
    </div>
  );
}

export default function GPUCards({ stateless, stateful }: GPUCardsProps) {
  return (
    <div className="metric-card">
      <h3 className="text-lg font-semibold mb-6">GPU Utilization</h3>

      <div className="grid grid-cols-2 gap-6">
        {/* Stateless GPUs */}
        <div>
          <h4 className="text-sm font-semibold text-slate-400 mb-4">Stateless (Round-Robin)</h4>
          <div className="space-y-4">
            {stateless?.gpu0 && (
              <GPUCard
                gpuId="GPU0"
                hbmUtil={stateless.gpu0.hbm_utilization}
                cacheHitRate={stateless.gpu0.cache_hit_rate}
                blocks={stateless.gpu0.num_cached_blocks}
                activeRequests={stateless.gpu0.active_requests}
                color={getUtilizationColor(stateless.gpu0.hbm_utilization)}
              />
            )}
            {stateless?.gpu1 && (
              <GPUCard
                gpuId="GPU1"
                hbmUtil={stateless.gpu1.hbm_utilization}
                cacheHitRate={stateless.gpu1.cache_hit_rate}
                blocks={stateless.gpu1.num_cached_blocks}
                activeRequests={stateless.gpu1.active_requests}
                color={getUtilizationColor(stateless.gpu1.hbm_utilization)}
              />
            )}
          </div>
        </div>

        {/* Stateful GPUs */}
        <div>
          <h4 className="text-sm font-semibold text-slate-400 mb-4">Stateful (Prefix-Aware)</h4>
          <div className="space-y-4">
            {stateful?.gpu0 && (
              <GPUCard
                gpuId="GPU0"
                hbmUtil={stateful.gpu0.hbm_utilization}
                cacheHitRate={stateful.gpu0.cache_hit_rate}
                blocks={stateful.gpu0.num_cached_blocks}
                activeRequests={stateful.gpu0.active_requests}
                color={getUtilizationColor(stateful.gpu0.hbm_utilization)}
              />
            )}
            {stateful?.gpu1 && (
              <GPUCard
                gpuId="GPU1"
                hbmUtil={stateful.gpu1.hbm_utilization}
                cacheHitRate={stateful.gpu1.cache_hit_rate}
                blocks={stateful.gpu1.num_cached_blocks}
                activeRequests={stateful.gpu1.active_requests}
                color={getUtilizationColor(stateful.gpu1.hbm_utilization)}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
