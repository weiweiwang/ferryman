import { useCallback, useEffect, useRef, useState } from 'react';

export interface Task {
  id: string;
  title: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'canceled';
  progress?: string;
  updated_at?: string;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface ToolActivityPayload {
  run_id: string;
  event_id?: string;
  seq?: number;
  tool_name: string;
  phase: 'start' | 'running' | 'complete' | 'error';
  input?: Record<string, any>;
  duration_ms?: number;
  output?: string;
}

export interface RefreshPayload {
  entity: 'task' | 'schedule' | 'skill' | 'session';
  action: 'created' | 'updated' | 'deleted' | 'bulk';
  entity_id?: string;
  delta?: Record<string, any>;
}

export interface FerrymanEvent {
  namespace: string;
  event: string;
  session_id?: string;
  ts: string;
  payload: ToolActivityPayload | RefreshPayload | any;
}

export function mergeToolActivity(
  previous: ToolActivityPayload[],
  payload: ToolActivityPayload,
): ToolActivityPayload[] {
  if (payload.phase === 'start') {
    return [...previous, payload];
  }

  const idx = previous
    .slice()
    .reverse()
    .findIndex((activity) => (
      activity.run_id === payload.run_id &&
      activity.tool_name === payload.tool_name &&
      activity.phase === 'start'
    ));

  if (idx === -1) {
    return [...previous, payload];
  }

  const realIdx = previous.length - 1 - idx;
  const next = [...previous];
  next[realIdx] = {
    ...next[realIdx],
    phase: payload.phase,
    duration_ms: payload.duration_ms,
    output: payload.output,
  };
  return next;
}

export function useBackendConnection(url: string | null) {
  const [isConnected, setIsConnected] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [toolActivities, setToolActivities] = useState<ToolActivityPayload[]>([]);
  const [lastEvent, setLastEvent] = useState<FerrymanEvent | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pendingCalls = useRef<Map<number, { resolve: (val: any) => void; reject: (reason: any) => void }>>(new Map());

  useEffect(() => {
    if (!url) {
      setIsConnected(false);
      return;
    }

    const connect = () => {
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        setIsConnected(true);
      };

      socket.onclose = () => {
        setIsConnected(false);
        pendingCalls.current.forEach(({ reject }) => reject(new Error('WebSocket disconnected')));
        pendingCalls.current.clear();
        reconnectTimeoutRef.current = window.setTimeout(connect, 2000);
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.id && pendingCalls.current.has(data.id)) {
          const { resolve, reject } = pendingCalls.current.get(data.id)!;
          pendingCalls.current.delete(data.id);
          if (data.error) reject(data.error);
          else resolve(data.result);
          return;
        }

        if (data.method === 'ferryman_event') {
          const evt = data.params as FerrymanEvent;
          setLastEvent(evt);
          if (evt.namespace === "agent" && evt.event === "tool_activity") {
            console.debug('[ferryman][tool_activity]', {
              runId: evt.payload.run_id,
              eventId: evt.payload.event_id,
              seq: evt.payload.seq,
              toolName: evt.payload.tool_name,
              phase: evt.payload.phase,
            });
            setToolActivities((prev) => mergeToolActivity(prev, evt.payload));
          }
          return;
        }
      };

      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      if (socketRef.current) {
        socketRef.current.close();
      }
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      pendingCalls.current.forEach(({ reject }) => reject(new Error('WebSocket disconnected')));
      pendingCalls.current.clear();
    };
  }, [url]);

  const call = useCallback((method: string, params: any = {}) => {
    return new Promise((resolve, reject) => {
      if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'));
        return;
      }

      const id = Date.now() + Math.floor(Math.random() * 1000);
      pendingCalls.current.set(id, { resolve, reject });
      socketRef.current.send(JSON.stringify({
        jsonrpc: '2.0',
        method,
        params,
        id,
      }));
    });
  }, []);

  const execute = useCallback((instruction: string, sessionId: string) => {
    return call('execute', { instruction, session_id: sessionId });
  }, [call]);

  const cancelRun = useCallback((runId: string, sessionId?: string) => {
    return call('cancel_run', sessionId ? { run_id: runId, session_id: sessionId } : { run_id: runId });
  }, [call]);

  const refreshTasks = useCallback(async () => {
    const result: any = await call('list_tasks');
    setTasks(Array.isArray(result) ? result : (result?.tasks || []));
  }, [call]);

  const clearToolActivities = useCallback(() => setToolActivities([]), []);

  return {
    call,
    execute,
    cancelRun,
    isConnected,
    tasks,
    toolActivities,
    lastEvent,
    refreshTasks,
    clearToolActivities,
  };
}
