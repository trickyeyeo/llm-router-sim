interface ProgressIndicatorProps {
  progress: number;
  currentTime: number;
  totalTime: number;
  requestsStateless?: { generated: number; completed: number };
  requestsStateful?: { generated: number; completed: number };
}

export default function ProgressIndicator({
  progress,
  currentTime,
  totalTime,
  requestsStateless,
  requestsStateful,
}: ProgressIndicatorProps) {
  const progressPercent = Math.min(100, Math.round(progress * 100));
  const currentTimeSec = (currentTime / 1000).toFixed(1);
  const totalTimeSec = (totalTime / 1000).toFixed(1);

  return (
    <div className="metric-card">
      <h3 className="text-lg font-semibold mb-4">Simulation Progress</h3>

      {/* Progress Bar */}
      <div className="mb-6">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progressPercent}%` }}></div>
        </div>
        <p className="text-center text-sm text-slate-400 mt-2">{progressPercent}% complete</p>
      </div>

      {/* Time and Requests */}
      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <p className="text-slate-400">Simulation Time</p>
          <p className="font-semibold text-lg">
            {currentTimeSec}s / {totalTimeSec}s
          </p>
        </div>

        <div>
          <p className="text-slate-400">Stateless Requests</p>
          <p className="font-semibold text-lg">
            {requestsStateless?.completed} / {requestsStateless?.generated}
          </p>
        </div>

        <div>
          <p className="text-slate-400">Stateful Requests</p>
          <p className="font-semibold text-lg">
            {requestsStateful?.completed} / {requestsStateful?.generated}
          </p>
        </div>
      </div>
    </div>
  );
}
