import { useCallback, useEffect, useState } from 'react';
import type { Usage } from './useBackendConnection';
import { translateStatic } from './useI18n';

export interface Message {
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  metadata?: {
    state?: 'pending' | 'failed';
    error?: string;
    usage?: Usage;
    [key: string]: any;
  };
}

export interface Session {
  id: string;
  title: string;
  updated_at: string;
  input_tokens: number;
  output_tokens: number;
}

interface UseSessionsArgs {
  call: (method: string, params?: any) => Promise<any>;
  executeInstruction: (instruction: string, sessionId: string) => Promise<any>;
  clearToolActivities: () => void;
}

export function useSessions({
  call,
  executeInstruction,
  clearToolActivities,
}: UseSessionsArgs) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => localStorage.getItem('last_session_id') || 'default');
  const [currentUsage, setCurrentUsage] = useState<Usage>({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
  const [isExecuting, setIsExecuting] = useState(false);

  useEffect(() => {
    if (currentSessionId) {
      localStorage.setItem('last_session_id', currentSessionId);
    }
  }, [currentSessionId]);

  const refreshSessions = useCallback(async () => {
    try {
      const res: any = await call('list_sessions', { limit: 50 });
      setSessions(res.sessions || []);
    } catch (error) {
      console.error('Failed to list sessions:', error);
    }
  }, [call]);

  const switchSession = useCallback(async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    try {
      const res: any = await call('get_messages', { session_id: sessionId, limit: 100 });
      setMessages(res.messages || []);

      const sessionInfo = sessions.find((session) => session.id === sessionId);
      if (sessionInfo) {
        setCurrentUsage({
          input_tokens: sessionInfo.input_tokens,
          output_tokens: sessionInfo.output_tokens,
          total_tokens: sessionInfo.input_tokens + sessionInfo.output_tokens,
        });
      } else {
        setCurrentUsage({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
      }
    } catch (error) {
      console.error('Failed to load session messages:', error);
    }
  }, [call, sessions]);

  const createNewSession = useCallback(async () => {
    const newId = crypto.randomUUID();
    setCurrentSessionId(newId);
    setMessages([]);
    setCurrentUsage({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });

    try {
      await call('create_session', { session_id: newId });
      await refreshSessions();
    } catch (error) {
      console.error('Failed to create session:', error);
    }

    return newId;
  }, [call, refreshSessions]);

  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      await call('delete_session', { session_id: sessionId });
      await refreshSessions();
      if (currentSessionId === sessionId) {
        await switchSession('default');
      }
    } catch (error) {
      console.error('Failed to delete session:', error);
    }
  }, [call, currentSessionId, refreshSessions, switchSession]);

  const execute = useCallback(async (instruction: string) => {
    if (!instruction.trim()) return;
    const pendingMessageId = crypto.randomUUID();

    setIsExecuting(true);
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: instruction },
      {
        id: pendingMessageId,
        role: 'assistant',
        content: '',
        metadata: { state: 'pending' },
      },
    ]);

    try {
      clearToolActivities();
      const result = await executeInstruction(instruction, currentSessionId);
      
      // result is now FerrymanEventEnvelope format
      const payload = result?.payload;
      if (!payload) {
        throw new Error(translateStatic('chat.run_failed'));
      }

      const usage = payload.usage || { input_tokens: 0, output_tokens: 0, total_tokens: 0 };
      const responseMessages = payload.messages || [];
      const latestAssistantResponse = responseMessages.reverse().find((m: any) => m.role === 'assistant')?.content || '';

      setMessages((prev) => prev.map((message) => (
        message.id === pendingMessageId
          ? {
              ...message,
              content: latestAssistantResponse,
              metadata: { usage },
            }
          : message
      )));

      setCurrentUsage((prev) => ({
        input_tokens: prev.input_tokens + (usage.input_tokens || 0),
        output_tokens: prev.output_tokens + (usage.output_tokens || 0),
        total_tokens: prev.total_tokens + (usage.total_tokens || 0),
      }));

      await refreshSessions();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setMessages((prev) => prev.map((item) => (
        item.id === pendingMessageId
          ? {
              ...item,
              content: `${translateStatic('chat.run_failed')}\n\n${translateStatic('common.error_prefix')}: ${message}`,
              metadata: { state: 'failed', error: message },
            }
          : item
      )));
    } finally {
      setIsExecuting(false);
    }
  }, [currentSessionId, executeInstruction, refreshSessions]);

  return {
    messages,
    setMessages,
    sessions,
    currentSessionId,
    currentUsage,
    refreshSessions,
    switchSession,
    createNewSession,
    deleteSession,
    execute,
    isExecuting,
  };
}
