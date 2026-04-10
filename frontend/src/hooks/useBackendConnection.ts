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
  tool_name: string;
  phase: 'start' | 'running' | 'complete' | 'error';
  input?: Record<string, any>;
  duration_ms?: number;
}

export interface FerrymanEvent {
  namespace: string;
  event: string;
  session_id?: string;
  ts: string;
  payload: any;
}

export function useBackendConnection(url: string | null) {
  const [isConnected, setIsConnected] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [toolActivities, setToolActivities] = useState<ToolActivityPayload[]>([]);

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

        if (data.method === 'task_update') {
          const update = data.params;
          setTasks((prev) => {
            const exists = prev.find((task) => task.id === update.id);
            if (exists) {
              return prev.map((task) => (task.id === update.id ? { ...task, ...update } : task));
            }
            return [...prev, update];
          });
          return;
        }

        if (data.method === 'ferryman_event') {
          const evt = data.params as FerrymanEvent;
          if (evt.namespace === "agent" && evt.event === "tool_activity") {
            setToolActivities((prev) => {
               // Update phase manually for the same tool + run? 
               // Wait, phase complete/error usually follows a start. Let's just append sequentially to simulate a streaming log.
               // Actually we can keep a flat log of tool phases. But replacing the start with complete is better for a nice checklist UI.
               const isStart = evt.payload.phase === 'start';
               if (isStart) {
                   return [...prev, evt.payload];
               } else {
                   // Replace the last matching start event
                   const idx = prev.slice().reverse().findIndex(p => p.run_id === evt.payload.run_id && p.tool_name === evt.payload.tool_name && p.phase === 'start');
                   if (idx !== -1) {
                       const realIdx = prev.length - 1 - idx;
                       const newArr = [...prev];
                       newArr[realIdx] = { ...newArr[realIdx], phase: evt.payload.phase, duration_ms: evt.payload.duration_ms };
                       return newArr;
                   }
                   return [...prev, evt.payload];
               }
            });
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

  const refreshTasks = useCallback(async () => {
    const result = await call('list_tasks');
    setTasks(Array.isArray(result) ? result : []);
  }, [call]);

  const clearToolActivities = useCallback(() => setToolActivities([]), []);

  return {
    call,
    execute,
    isConnected,
    tasks,
    toolActivities,
    refreshTasks,
    clearToolActivities,
  };
}
