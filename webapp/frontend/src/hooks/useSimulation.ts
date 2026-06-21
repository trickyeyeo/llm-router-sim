import { useState, useEffect } from 'react';

interface SimState {
  progress: number;
  current_time_ms: number;
  total_time_ms: number;
  comparisonMode?: string;
  left?: {
    label: string;
    gpus: any;
    requests: { generated: number; completed: number };
  };
  right?: {
    label: string;
    gpus: any;
    requests: { generated: number; completed: number };
  };
  final_metrics?: {
    left: any;
    right: any;
  };
}

export interface SimulationParams {
  num_sessions: number;
  turns_per_session: number;
  failure_rate: number;
  network_type: string;
  hbm_percent?: number;
  comparisonMode?: 'stateless_vs_stateful' | 'stateful_baseline_vs_with_p2p';
  baselineFailureRate?: number;
}

export function useSimulation(params: SimulationParams, shouldRun: boolean) {
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
      comparisonMode: params.comparisonMode || 'stateless_vs_stateful',
    });

    const comparisonMode = params.comparisonMode || 'stateless_vs_stateful';

    // For single-run modes: run once and map results to left/right
    if (comparisonMode === 'stateless_vs_stateful') {
      runSingleSimulation(
        params.num_sessions,
        params.turns_per_session,
        params.failure_rate,
        params.network_type,
        params.hbm_percent || 0,
        'Stateless',
        'Stateful',
        setSimState,
        setRunning
      );
    } else if (comparisonMode === 'stateful_baseline_vs_with_p2p') {
      // Run baseline first, then with P2P
      runBaselineAndWithP2P(
        params.num_sessions,
        params.turns_per_session,
        params.baselineFailureRate || 0,
        params.failure_rate,
        params.network_type,
        params.hbm_percent || 0,
        setSimState,
        setRunning
      );
    }
  }, [shouldRun, params]);

  return { simState, running };
}

function runSingleSimulation(
  num_sessions: number,
  turns: number,
  failureRate: number,
  networkType: string,
  hbmPercent: number,
  leftLabel: string,
  rightLabel: string,
  setState: React.Dispatch<React.SetStateAction<SimState>>,
  setRunning: React.Dispatch<React.SetStateAction<boolean>>
) {
  const query = new URLSearchParams({
    num_sessions: num_sessions.toString(),
    turns_per_session: turns.toString(),
    failure_rate: failureRate.toString(),
    network_type: networkType,
    hbm_percent: hbmPercent.toString(),
  });

  const eventSource = new EventSource(`/simulate?${query}`);

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'heartbeat') {
        setState((prev) => ({
          ...prev,
          progress: data.progress,
          current_time_ms: data.current_time_ms,
          total_time_ms: data.total_time_ms,
          left: {
            label: leftLabel,
            gpus: data.stateless?.gpus,
            requests: data.stateless?.requests || { generated: 0, completed: 0 },
          },
          right: {
            label: rightLabel,
            gpus: data.stateful?.gpus,
            requests: data.stateful?.requests || { generated: 0, completed: 0 },
          },
        }));
      } else if (data.type === 'complete') {
        setState((prev) => ({
          ...prev,
          progress: 1,
          final_metrics: {
            left: data.stateless,
            right: data.stateful,
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
}

function runBaselineAndWithP2P(
  num_sessions: number,
  turns: number,
  baselineFailureRate: number,
  withP2pFailureRate: number,
  networkType: string,
  hbmPercent: number,
  setState: React.Dispatch<React.SetStateAction<SimState>>,
  setRunning: React.Dispatch<React.SetStateAction<boolean>>
) {
  let baselineMetrics: any = null;

  const runBaseline = () => {
    const query = new URLSearchParams({
      num_sessions: num_sessions.toString(),
      turns_per_session: turns.toString(),
      failure_rate: baselineFailureRate.toString(),
      network_type: networkType,
      hbm_percent: hbmPercent.toString(),
      enable_p2p_recovery: 'false',
    });

    const eventSource = new EventSource(`/simulate?${query}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'complete') {
          baselineMetrics = data.stateful;
          eventSource.close();
          runWithP2P();
        }
      } catch (err) {
        console.error('Error parsing SSE data:', err);
      }
    };
  };

  const runWithP2P = () => {
    const query = new URLSearchParams({
      num_sessions: num_sessions.toString(),
      turns_per_session: turns.toString(),
      failure_rate: withP2pFailureRate.toString(),
      network_type: networkType,
      hbm_percent: hbmPercent.toString(),
      enable_p2p_recovery: 'true',
    });

    const eventSource = new EventSource(`/simulate?${query}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'heartbeat') {
          setState((prev) => ({
            ...prev,
            progress: data.progress * 0.5 + 0.5, // Second run is 50-100% of progress
            current_time_ms: data.current_time_ms,
            total_time_ms: data.total_time_ms,
            left: {
              label: 'Baseline (20% failures, no recovery)',
              gpus: baselineMetrics?.gpus,
              requests: baselineMetrics?.requests || { generated: 0, completed: 0 },
            },
            right: {
              label: 'With P2P Recovery',
              gpus: data.stateful?.gpus,
              requests: data.stateful?.requests || { generated: 0, completed: 0 },
            },
          }));
        } else if (data.type === 'complete') {
          setState((prev) => ({
            ...prev,
            progress: 1,
            final_metrics: {
              left: baselineMetrics,
              right: data.stateful,
            },
          }));
          eventSource.close();
          setRunning(false);
        }
      } catch (err) {
        console.error('Error parsing SSE data:', err);
      }
    };
  };

  runBaseline();
}

