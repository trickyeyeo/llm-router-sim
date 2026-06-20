import { useState, useEffect } from 'react';

interface SimState {
  progress: number;
  current_time_ms: number;
  total_time_ms: number;
  stateless?: {
    gpus: any;
    requests: { generated: number; completed: number };
  };
  stateful?: {
    gpus: any;
    requests: { generated: number; completed: number };
  };
  final_metrics?: {
    stateless: any;
    stateful: any;
  };
}

export function useSimulation(
  params: { num_sessions: number; turns_per_session: number },
  shouldRun: boolean
) {
  const [simState, setSimState] = useState<SimState>({
    progress: 0,
    current_time_ms: 0,
    total_time_ms: 35000,
  });

  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (!shouldRun) return;

    setRunning(true);
    setSimState({
      progress: 0,
      current_time_ms: 0,
      total_time_ms: 35000,
    });

    const query = new URLSearchParams({
      num_sessions: params.num_sessions.toString(),
      turns_per_session: params.turns_per_session.toString(),
    });

    const eventSource = new EventSource(`http://localhost:8000/simulate?${query}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'heartbeat') {
          setSimState((prev) => ({
            ...prev,
            progress: data.progress,
            current_time_ms: data.current_time_ms,
            total_time_ms: data.total_time_ms,
            stateless: data.stateless,
            stateful: data.stateful,
          }));
        } else if (data.type === 'complete') {
          setSimState((prev) => ({
            ...prev,
            progress: 1,
            final_metrics: {
              stateless: data.stateless,
              stateful: data.stateful,
            },
          }));
          eventSource.close();
          setRunning(false);
        }
      } catch (err) {
        console.error('Error parsing SSE data:', err);
      }
    };

    eventSource.onerror = () => {
      console.error('EventSource error');
      eventSource.close();
      setRunning(false);
    };

    return () => eventSource.close();
  }, [shouldRun, params]);

  return { simState, running };
}
