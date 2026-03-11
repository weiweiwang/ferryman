import { useState, useEffect, useCallback, useRef } from 'react';

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  metadata?: any;
}

export interface Task {
  id: string;
  title: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  progress?: number;
}

export interface Session {
  id: string;
  title: string;
  updated_at: string;
  input_tokens: number;
  output_tokens: number;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export const useWebSocket = (url: string) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    return localStorage.getItem('last_session_id') || 'default';
  });
  const [currentUsage, setCurrentUsage] = useState<Usage>({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
  const [isConnected, setIsConnected] = useState(false);
  
  const socketRef = useRef<WebSocket | null>(null);
  const pendingCalls = useRef<Map<number, { resolve: (val: any) => void, reject: (reason: any) => void }>>(new Map());

  // Perspectives for persistence
  useEffect(() => {
    if (currentSessionId) {
      localStorage.setItem('last_session_id', currentSessionId);
    }
  }, [currentSessionId]);

  useEffect(() => {
    let reconnectTimeout: number;

    const connect = () => {
      console.log('Attempting to connect to Ferryman Backend...');
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        setIsConnected(true);
        console.log('Connected to Ferryman Backend');
      };

      socket.onclose = () => {
        setIsConnected(false);
        console.log('Disconnected from Ferryman Backend, retrying in 2s...');
        reconnectTimeout = window.setTimeout(connect, 2000);
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        // Handle Request-Response pattern
        if (data.id && pendingCalls.current.has(data.id)) {
          const { resolve, reject } = pendingCalls.current.get(data.id)!;
          pendingCalls.current.delete(data.id);
          if (data.error) reject(data.error);
          else resolve(data.result);
          return;
        }

        // Handle background notifications
        if (data.result && data.result.status === 'success' && data.result.response) {
          if (data.result.session_id === currentSessionId) {
            setMessages(prev => [...prev, { role: 'assistant', content: data.result.response, metadata: data.result.usage }]);
            if (data.result.usage) {
              setCurrentUsage(prev => ({
                input_tokens: prev.input_tokens + (data.result.usage.input_tokens || 0),
                output_tokens: prev.output_tokens + (data.result.usage.output_tokens || 0),
                total_tokens: prev.total_tokens + (data.result.usage.total_tokens || 0)
              }));
            }
          }
        } else if (data.method === 'task_update') {
          const update = data.params;
          setTasks(prev => {
            const exists = prev.find(t => t.id === update.id);
            if (exists) {
              return prev.map(t => t.id === update.id ? { ...t, ...update } : t);
            }
            return [...prev, update];
          });
        } else if (data.error) {
          console.error('JSON-RPC Error:', data.error);
          setMessages(prev => [...prev, { role: 'system', content: `Error: ${data.error.message}` }]);
        }
      };

      socket.onerror = (err) => {
        console.error('WebSocket Error:', err);
        socket.close();
      };
    };

    connect();

    return () => {
      if (socketRef.current) socketRef.current.close();
      clearTimeout(reconnectTimeout);
    };
  }, [url, currentSessionId]);

  const call = useCallback((method: string, params: any = {}) => {
    return new Promise((resolve, reject) => {
      if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'));
        return;
      }

      const id = Date.now() + Math.floor(Math.random() * 1000);
      const req = {
        jsonrpc: '2.0',
        method,
        params,
        id
      };

      pendingCalls.current.set(id, { resolve, reject });
      socketRef.current.send(JSON.stringify(req));
    });
  }, []);

  const execute = useCallback((instruction: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return;

    const req = {
      jsonrpc: '2.0',
      method: 'execute',
      params: { instruction, session_id: currentSessionId },
      id: Date.now()
    };

    setMessages(prev => [...prev, { role: 'user', content: instruction }]);
    socketRef.current.send(JSON.stringify(req));
  }, [currentSessionId]);

  const refreshSessions = useCallback(async () => {
     try {
       const res: any = await call('list_sessions', { limit: 50 });
       setSessions(res.sessions || []);
     } catch (e) {
       console.error('Failed to list sessions:', e);
     }
  }, [call]);

  const switchSession = useCallback(async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    try {
      const res: any = await call('get_messages', { session_id: sessionId, limit: 100 });
      setMessages(res.messages || []);
      
      // Calculate current session usage from sessions list if available or 0 initially
      const sessionInfo = sessions.find(s => s.id === sessionId);
      if (sessionInfo) {
        setCurrentUsage({
          input_tokens: sessionInfo.input_tokens,
          output_tokens: sessionInfo.output_tokens,
          total_tokens: sessionInfo.input_tokens + sessionInfo.output_tokens
        });
      } else {
        setCurrentUsage({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
      }
    } catch (e) {
      console.error('Failed to load session messages:', e);
    }
  }, [call, sessions]);

  const createNewSession = useCallback(async () => {
    const newId = crypto.randomUUID();
    setCurrentSessionId(newId);
    setMessages([]);
    setCurrentUsage({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
    // We don't necessarily need to call create_session RPC immediately, 
    // it will be created on first message in kernel.py. 
    // But for listing purposes, it's better to stay in sync.
    try {
      await call('create_session', { id: newId, title: "New Chat" });
      await refreshSessions();
    } catch (e) {
      console.error('Failed to create session:', e);
    }
    return newId;
  }, [call, refreshSessions]);

  const deleteSession = useCallback(async (sessionId: string) => {
     try {
       await call('delete_session', { session_id: sessionId });
       await refreshSessions();
       if (currentSessionId === sessionId) {
         switchSession('default');
       }
     } catch (e) {
       console.error('Failed to delete session:', e);
     }
  }, [call, currentSessionId, refreshSessions, switchSession]);

  return { 
    messages, setMessages, 
    tasks, setTasks, 
    sessions, currentSessionId, 
    currentUsage, isConnected, 
    execute, call,
    refreshSessions, switchSession, createNewSession, deleteSession
  };
};
