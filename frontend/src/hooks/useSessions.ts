import { useCallback, useEffect, useRef, useState } from 'react';
import type { FerrymanEvent, RefreshPayload, Usage } from './useBackendConnection';
import { translateStatic } from './useI18n';

const MESSAGE_PAGE_SIZE = 20;

export type MessageRunStatus = 'pending' | 'success' | 'failed' | 'canceled';

export interface MessageRunMetadata {
  id?: string;
  status?: MessageRunStatus;
  scope?: string;
  error?: string;
  [key: string]: any;
}

export interface MessageMetadata {
  run?: MessageRunMetadata;
  usage?: Usage;
  model?: {
    name?: string | null;
    provider?: string | null;
    [key: string]: any;
  };
  [key: string]: any;
}

export interface Message {
  id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
  metadata?: MessageMetadata;
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
  cancelRun: (runId: string, sessionId?: string) => Promise<any>;
  clearToolActivities: () => void;
  lastEvent: FerrymanEvent | null;
  isConnected?: boolean;
}

type ActiveRun = {
  runId: string;
  sessionId: string;
};

type TerminalRunSnapshot = {
  status: MessageRunStatus;
  usage: Usage;
};

export type ExecuteStatus = 'started' | 'busy' | 'error';

export interface ExecuteResult {
  status: ExecuteStatus;
  message?: string;
  runId?: string;
}

export function useSessions({
  call,
  executeInstruction,
  cancelRun,
  clearToolActivities,
  lastEvent,
  isConnected = false,
}: UseSessionsArgs) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>('');
  const [currentUsage, setCurrentUsage] = useState<Usage>({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [olderMessagesCursor, setOlderMessagesCursor] = useState<string | null>(null);
  const [isLoadingOlderMessages, setIsLoadingOlderMessages] = useState(false);
  const currentSessionIdRef = useRef(currentSessionId);
  const sessionsRef = useRef(sessions);
  const activeRunRef = useRef(activeRun);
  const messagesRef = useRef(messages);
  const olderMessagesCursorRef = useRef<string | null>(olderMessagesCursor);
  const isLoadingOlderMessagesRef = useRef(isLoadingOlderMessages);
  const hasInitializedSessionRef = useRef(false);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  useEffect(() => {
    activeRunRef.current = activeRun;
  }, [activeRun]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    olderMessagesCursorRef.current = olderMessagesCursor;
  }, [olderMessagesCursor]);

  useEffect(() => {
    isLoadingOlderMessagesRef.current = isLoadingOlderMessages;
  }, [isLoadingOlderMessages]);

  const refreshSessions = useCallback(async () => {
    try {
      const res: any = await call('list_sessions', { limit: 50 });
      const nextSessions = (res.sessions || []) as Session[];
      sessionsRef.current = nextSessions;
      setSessions(nextSessions);
      return nextSessions;
    } catch (error) {
      console.error('Failed to list sessions:', error);
      return [] as Session[];
    }
  }, [call]);

  const getTerminalRunSnapshot = useCallback((candidateMessages: Message[], runId: string): TerminalRunSnapshot | null => {
    const runMessages = candidateMessages.filter((message) => message.metadata?.run?.id === runId);
    const latestAssistantMessage = [...runMessages]
      .reverse()
      .find((message) => message.role === 'assistant' && message.metadata?.run?.status && message.metadata.run.status !== 'pending');
    const latestUserMessage = [...runMessages]
      .reverse()
      .find((message) => message.role === 'user' && message.metadata?.run?.status && message.metadata.run.status !== 'pending');

    const status = latestAssistantMessage?.metadata?.run?.status || latestUserMessage?.metadata?.run?.status;
    if (!status || status === 'pending') {
      return null;
    }

    return {
      status,
      usage: latestAssistantMessage?.metadata?.usage || { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
    };
  }, []);

  const reconcileActiveRunFromMessages = useCallback((candidateMessages: Message[], sessionId: string) => {
    const currentActiveRun = activeRunRef.current;
    if (!currentActiveRun || sessionId !== currentActiveRun.sessionId) {
      return false;
    }

    const snapshot = getTerminalRunSnapshot(candidateMessages, currentActiveRun.runId);
    if (!snapshot) {
      return false;
    }

    if (currentSessionIdRef.current === sessionId) {
      setMessages(candidateMessages);
      setCurrentUsage((prev) => ({
        input_tokens: prev.input_tokens + (snapshot.usage.input_tokens || 0),
        output_tokens: prev.output_tokens + (snapshot.usage.output_tokens || 0),
        total_tokens: prev.total_tokens + (snapshot.usage.total_tokens || 0),
      }));
    }

    activeRunRef.current = null;
    setActiveRun(null);
    clearToolActivities();
    refreshSessions().catch((error) => {
      console.error('Failed to refresh sessions after run reconciliation:', error);
    });
    return true;
  }, [clearToolActivities, getTerminalRunSnapshot, refreshSessions]);

  const mergePendingAssistantPlaceholder = useCallback((candidateMessages: Message[], sessionId: string): Message[] => {
    const currentActiveRun = activeRunRef.current;
    if (!currentActiveRun || sessionId !== currentActiveRun.sessionId) {
      return candidateMessages;
    }

    if (getTerminalRunSnapshot(candidateMessages, currentActiveRun.runId)) {
      return candidateMessages;
    }

    const hasPendingAssistant = candidateMessages.some((message) =>
      message.role === 'assistant' &&
      message.metadata?.run?.id === currentActiveRun.runId &&
      message.metadata?.run?.status === 'pending'
    );
    if (hasPendingAssistant) {
      return candidateMessages;
    }

    const existingPlaceholder = messagesRef.current.find((message) =>
      message.role === 'assistant' &&
      message.metadata?.run?.id === currentActiveRun.runId &&
      message.metadata?.run?.status === 'pending'
    );

    if (!existingPlaceholder) {
      const pendingPlaceholder: Message = {
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString(),
        metadata: {
          run: {
            id: currentActiveRun.runId,
            status: 'pending',
            scope: 'master',
          },
        },
      };

      return [
        ...candidateMessages,
        pendingPlaceholder,
      ];
    }

    return [...candidateMessages, existingPlaceholder];
  }, [getTerminalRunSnapshot]);

  const switchSession = useCallback(async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    currentSessionIdRef.current = sessionId;
    setOlderMessagesCursor(null);
    try {
      const res: any = await call('list_messages', { session_id: sessionId, limit: MESSAGE_PAGE_SIZE });
      if (currentSessionIdRef.current !== sessionId) {
        return;
      }

      const nextMessages = mergePendingAssistantPlaceholder(res.messages || [], sessionId);
      setMessages(nextMessages);
      setOlderMessagesCursor(res.next_cursor || null);
      const reconciledActiveRun = reconcileActiveRunFromMessages(nextMessages, sessionId);

      const sessionInfo = sessionsRef.current.find((session) => session.id === sessionId);
      if (sessionInfo) {
        setCurrentUsage({
          input_tokens: sessionInfo.input_tokens,
          output_tokens: sessionInfo.output_tokens,
          total_tokens: sessionInfo.input_tokens + sessionInfo.output_tokens,
        });
      } else if (!reconciledActiveRun) {
        setCurrentUsage({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
      }
    } catch (error) {
      console.error('Failed to load session messages:', error);
    }
  }, [call, mergePendingAssistantPlaceholder, reconcileActiveRunFromMessages]);

  const refreshCurrentSession = useCallback(async () => {
    const sessionId = currentSessionIdRef.current;
    if (!sessionId) {
      return;
    }

    try {
      const res: any = await call('list_messages', { session_id: sessionId, limit: MESSAGE_PAGE_SIZE });
      if (currentSessionIdRef.current !== sessionId) {
        return;
      }

      const nextMessages = mergePendingAssistantPlaceholder(res.messages || [], sessionId);
      setMessages(nextMessages);
      setOlderMessagesCursor(res.next_cursor || null);

      const reconciledActiveRun = reconcileActiveRunFromMessages(nextMessages, sessionId);
      if (reconciledActiveRun) {
        return;
      }

      const sessionInfo = sessionsRef.current.find((session) => session.id === sessionId);
      if (sessionInfo) {
        setCurrentUsage({
          input_tokens: sessionInfo.input_tokens,
          output_tokens: sessionInfo.output_tokens,
          total_tokens: sessionInfo.input_tokens + sessionInfo.output_tokens,
        });
      }
    } catch (error) {
      console.error('Failed to refresh current session messages:', error);
    }
  }, [call, mergePendingAssistantPlaceholder, reconcileActiveRunFromMessages]);

  useEffect(() => {
    if (!isConnected) {
      return;
    }

    if (!hasInitializedSessionRef.current) {
      return;
    }

    if (!currentSessionIdRef.current) {
      return;
    }

    refreshCurrentSession().catch((error) => {
      console.error('Failed to refresh current session on connect:', error);
    });
  }, [isConnected, refreshCurrentSession]);

  useEffect(() => {
    if (!isConnected) {
      return;
    }

    const refreshIfVisible = () => {
      if (document.visibilityState !== 'visible') {
        return;
      }

      refreshCurrentSession().catch((error) => {
        console.error('Failed to refresh current session after visibility change:', error);
      });
    };

    const refreshOnFocus = () => {
      refreshCurrentSession().catch((error) => {
        console.error('Failed to refresh current session on focus:', error);
      });
    };

    document.addEventListener('visibilitychange', refreshIfVisible);
    window.addEventListener('focus', refreshOnFocus);

    return () => {
      document.removeEventListener('visibilitychange', refreshIfVisible);
      window.removeEventListener('focus', refreshOnFocus);
    };
  }, [isConnected, refreshCurrentSession]);

  useEffect(() => {
    if (!lastEvent || lastEvent.namespace !== 'data' || lastEvent.event !== 'refresh') {
      return;
    }

    const payload = lastEvent.payload as RefreshPayload;
    if (payload.entity !== 'session') {
      return;
    }

    refreshSessions().catch((error) => {
      console.error('Failed to refresh sessions after session event:', error);
    });
  }, [lastEvent, refreshSessions]);

  useEffect(() => {
    if (!lastEvent || lastEvent.namespace !== 'agent' || lastEvent.event !== 'chat_final' || !activeRun) {
      return;
    }

    const payload = lastEvent.payload as any;
    if (payload?.run_id !== activeRun.runId || lastEvent.session_id !== activeRun.sessionId) {
      return;
    }

    const usage = payload?.usage || { input_tokens: 0, output_tokens: 0, total_tokens: 0 };
    const responseMessages = Array.isArray(payload?.messages) ? payload.messages : [];
    const latestAssistantMessage = [...responseMessages].reverse().find((message: any) => message.role === 'assistant');
    const latestAssistantResponse = latestAssistantMessage?.content || '';
    const runMetadata = latestAssistantMessage?.metadata?.run || {};
    const runStatus: MessageRunStatus = runMetadata.status || (latestAssistantResponse.startsWith('Run failed:') ? 'failed' : 'success');
    const nextRunMetadata: MessageRunMetadata = {
      id: runMetadata.id || activeRun.runId,
      status: runStatus,
      scope: runMetadata.scope || 'master',
      ...(runMetadata.error ? { error: runMetadata.error } : {}),
    };
    const isVisibleRunSession = currentSessionId === activeRun.sessionId;

    if (isVisibleRunSession) {
      setMessages((prev) => {
        if (runStatus === 'canceled') {
          return prev
            .filter((message) => !(
              message.role === 'assistant' &&
              message.metadata?.run?.id === activeRun.runId &&
              message.metadata?.run?.status === 'pending'
            ))
            .map((message) => (
              message.role === 'user' && message.metadata?.run?.id === activeRun.runId
                ? {
                    ...message,
                    metadata: {
                      ...(message.metadata || {}),
                      run: nextRunMetadata,
                    },
                  }
                : message
            ));
        }

        const nextAssistantMetadata: MessageMetadata = {
          usage,
          run: nextRunMetadata,
        };

        if (latestAssistantMessage?.metadata?.model) {
          nextAssistantMetadata.model = latestAssistantMessage.metadata.model;
        }

        return prev.map((message) => {
          if (message.role === 'user' && message.metadata?.run?.id === activeRun.runId) {
            return {
              ...message,
              metadata: {
                ...(message.metadata || {}),
                run: nextRunMetadata,
              },
            };
          }

          if (
            message.role === 'assistant' &&
            message.metadata?.run?.id === activeRun.runId &&
            message.metadata?.run?.status === 'pending'
          ) {
            return {
              ...message,
              content: latestAssistantResponse,
              metadata: nextAssistantMetadata,
            };
          }

          return message;
        });
      });

      setCurrentUsage((prev) => ({
        input_tokens: prev.input_tokens + (usage.input_tokens || 0),
        output_tokens: prev.output_tokens + (usage.output_tokens || 0),
        total_tokens: prev.total_tokens + (usage.total_tokens || 0),
      }));
    }

    setActiveRun(null);
    clearToolActivities();
    refreshSessions().catch((error) => {
      console.error('Failed to refresh sessions after chat final event:', error);
    });
  }, [activeRun, clearToolActivities, currentSessionId, lastEvent, refreshSessions]);

  useEffect(() => {
    if (!activeRun || !lastEvent || lastEvent.namespace !== 'data' || lastEvent.event !== 'refresh') {
      return;
    }

    const payload = lastEvent.payload as RefreshPayload;
    const refreshedSessionId = lastEvent.session_id || payload.entity_id;
    if (payload.entity !== 'session' || refreshedSessionId !== activeRun.sessionId) {
      return;
    }

    let cancelled = false;

    call('list_messages', { session_id: activeRun.sessionId, limit: MESSAGE_PAGE_SIZE })
      .then((res: any) => {
        if (cancelled) {
          return;
        }

        reconcileActiveRunFromMessages(
          mergePendingAssistantPlaceholder(res.messages || [], activeRun.sessionId),
          activeRun.sessionId
        );
      })
      .catch((error) => {
        console.error('Failed to reconcile active run from session refresh:', error);
      });

    return () => {
      cancelled = true;
    };
  }, [activeRun, call, lastEvent, mergePendingAssistantPlaceholder, reconcileActiveRunFromMessages]);

  const createNewSession = useCallback(async () => {
    try {
      const res: any = await call('create_session', {});
      const newId = String(res?.id || '').trim();
      if (!newId) {
        throw new Error('Backend did not return a session id');
      }
      setCurrentSessionId(newId);
      currentSessionIdRef.current = newId;
      setMessages([]);
      setOlderMessagesCursor(null);
      setCurrentUsage({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
      await refreshSessions();
      return newId;
    } catch (error) {
      console.error('Failed to create session:', error);
      return currentSessionIdRef.current;
    }
  }, [call, refreshSessions]);

  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      await call('delete_session', { session_id: sessionId });
      const remainingSessions = (await refreshSessions()).filter((session) => session.id !== sessionId);
      if (currentSessionId === sessionId) {
        const nextSessionId = remainingSessions[0]?.id;
        if (nextSessionId) {
          await switchSession(nextSessionId);
        } else {
          await createNewSession();
        }
      }
    } catch (error) {
      console.error('Failed to delete session:', error);
    }
  }, [call, createNewSession, currentSessionId, refreshSessions, switchSession]);

  const execute = useCallback(async (instruction: string): Promise<ExecuteResult> => {
    const trimmedInstruction = instruction.trim();
    if (!trimmedInstruction) {
      return { status: 'error', message: translateStatic('chat.run_failed') };
    }
    if (activeRun || isSubmitting) {
      return { status: 'busy', message: translateStatic('chat.session_busy') };
    }

    const targetSessionId = currentSessionId;
    if (!targetSessionId) {
      return { status: 'error', message: translateStatic('chat.run_failed') };
    }
    setIsSubmitting(true);

    try {
      const result = await executeInstruction(trimmedInstruction, targetSessionId);
      const status = result?.status;
      const runId = result?.run_id;

      if (status === 'busy') {
        return {
          status: 'busy',
          message: result?.message || translateStatic('chat.session_busy'),
          runId,
        };
      }

      if (status !== 'started' || !runId) {
        throw new Error(result?.message || translateStatic('chat.run_failed'));
      }

      const nowIso = new Date().toISOString();

      clearToolActivities();
      setMessages((prev) => [
        ...prev,
        {
          role: 'user',
          content: trimmedInstruction,
          created_at: nowIso,
          metadata: {
            run: {
              id: runId,
              status: 'pending',
              scope: 'master',
            },
          },
        },
        {
          role: 'assistant',
          content: '',
          created_at: nowIso,
          metadata: { run: { id: runId, status: 'pending', scope: 'master' } },
        },
      ]);
      const nextActiveRun = { runId, sessionId: targetSessionId };
      activeRunRef.current = nextActiveRun;
      setActiveRun(nextActiveRun);
      return { status: 'started', runId };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { status: 'error', message };
    } finally {
      setIsSubmitting(false);
    }
  }, [activeRun, clearToolActivities, currentSessionId, executeInstruction, isSubmitting]);

  useEffect(() => {
    if (!isConnected || hasInitializedSessionRef.current) {
      return;
    }

    let cancelled = false;

    const initializeSession = async () => {
      const listedSessions = await refreshSessions();
      if (cancelled) {
        return;
      }

      const targetSessionId = listedSessions[0]?.id;
      hasInitializedSessionRef.current = true;

      if (targetSessionId) {
        await switchSession(targetSessionId);
        return;
      }

      await createNewSession();
    };

    initializeSession().catch((error) => {
      console.error('Failed to initialize session:', error);
    });

    return () => {
      cancelled = true;
    };
  }, [createNewSession, isConnected, refreshSessions, switchSession]);

  const stopActiveRun = useCallback(async () => {
    const runToStop = activeRunRef.current;
    if (!runToStop) return;

    if (currentSessionIdRef.current === runToStop.sessionId) {
      setMessages((prev) => prev
        .filter((message) => !(
          message.role === 'assistant' &&
          message.metadata?.run?.id === runToStop.runId &&
          message.metadata?.run?.status === 'pending'
        ))
        .map((message) => (
          message.role === 'user' && message.metadata?.run?.id === runToStop.runId
            ? {
                ...message,
                metadata: {
                  ...(message.metadata || {}),
                  run: {
                    ...(message.metadata?.run || {}),
                    id: runToStop.runId,
                    status: 'canceled',
                    scope: message.metadata?.run?.scope || 'master',
                  },
                },
              }
            : message
        )));
    }

    activeRunRef.current = null;
    setActiveRun(null);
    clearToolActivities();

    try {
      await cancelRun(runToStop.runId, runToStop.sessionId);
    } catch (error) {
      console.error('Failed to cancel active run:', error);
    }
  }, [cancelRun, clearToolActivities]);

  const loadOlderMessages = useCallback(async () => {
    const sessionId = currentSessionIdRef.current;
    const cursor = olderMessagesCursorRef.current;
    if (!sessionId || !cursor || isLoadingOlderMessagesRef.current) {
      return false;
    }

    isLoadingOlderMessagesRef.current = true;
    setIsLoadingOlderMessages(true);

    try {
      const res: any = await call('list_messages', {
        session_id: sessionId,
        limit: MESSAGE_PAGE_SIZE,
        cursor,
      });

      if (currentSessionIdRef.current !== sessionId) {
        return false;
      }

      const olderMessages = (res.messages || []) as Message[];
      setOlderMessagesCursor(res.next_cursor || null);
      setMessages((prev) => {
        const existingKeys = new Set(prev.map((message, index) => message.id || `${message.role}-${message.created_at || ''}-${index}`));
        const uniqueOlderMessages = olderMessages.filter((message, index) => {
          const key = message.id || `${message.role}-${message.created_at || ''}-${index}`;
          return !existingKeys.has(key);
        });
        return [...uniqueOlderMessages, ...prev];
      });

      return olderMessages.length > 0;
    } catch (error) {
      console.error('Failed to load older messages:', error);
      return false;
    } finally {
      isLoadingOlderMessagesRef.current = false;
      setIsLoadingOlderMessages(false);
    }
  }, [call]);

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
    loadOlderMessages,
    execute,
    stopActiveRun,
    hasOlderMessages: olderMessagesCursor !== null,
    isLoadingOlderMessages,
    isSubmitting,
    isExecuting: activeRun !== null,
  };
}
