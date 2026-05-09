import { useCallback, useEffect, useRef, useState } from 'react';
import type { FerrymanEvent, RefreshPayload, Usage } from './useBackendConnection';
import { translateStatic } from './useI18n';

const MESSAGE_PAGE_SIZE = 20;

export type MessageRunStatus = 'pending' | 'success' | 'failed' | 'canceled';

export interface MessageRunMetadata {
  id?: string;
  status?: MessageRunStatus;
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

export type SessionActiveRunStatus = 'running' | 'canceling';

export interface SessionActiveRun {
  run_id: string;
  status: SessionActiveRunStatus;
  started_at?: string;
}

export interface Session {
  id: string;
  title: string;
  updated_at: string;
  input_tokens: number;
  output_tokens: number;
  active_run?: SessionActiveRun | null;
}

interface UseSessionsArgs {
  call: (method: string, params?: any) => Promise<any>;
  executeInstruction: (instruction: string, sessionId: string) => Promise<any>;
  cancelRun: (runId: string, sessionId?: string) => Promise<any>;
  clearToolActivities: () => void;
  lastEvent: FerrymanEvent | null;
  isConnected?: boolean;
}

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
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [olderMessagesCursor, setOlderMessagesCursor] = useState<string | null>(null);
  const [isLoadingOlderMessages, setIsLoadingOlderMessages] = useState(false);
  const currentSessionIdRef = useRef(currentSessionId);
  const sessionsRef = useRef(sessions);
  const messagesRef = useRef(messages);
  const messagesSessionIdRef = useRef<string>('');
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
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    olderMessagesCursorRef.current = olderMessagesCursor;
  }, [olderMessagesCursor]);

  useEffect(() => {
    isLoadingOlderMessagesRef.current = isLoadingOlderMessages;
  }, [isLoadingOlderMessages]);

  const replaceSession = useCallback((nextSession: Session) => {
    const currentSessions = sessionsRef.current;
    const existingIndex = currentSessions.findIndex((session) => session.id === nextSession.id);
    const nextSessions = existingIndex >= 0
      ? currentSessions.map((session) => (session.id === nextSession.id ? nextSession : session))
      : [nextSession, ...currentSessions];
    sessionsRef.current = nextSessions;
    setSessions(nextSessions);
  }, []);

  const patchSession = useCallback((sessionId: string, patch: Partial<Session>) => {
    const currentSessions = sessionsRef.current;
    const existingIndex = currentSessions.findIndex((session) => session.id === sessionId);
    const nextSessions = existingIndex >= 0
      ? currentSessions.map((session) => (
        session.id === sessionId ? { ...session, ...patch } : session
      ))
      : [
        {
          id: sessionId,
          title: '',
          updated_at: new Date().toISOString(),
          input_tokens: currentUsage.input_tokens,
          output_tokens: currentUsage.output_tokens,
          active_run: null,
          ...patch,
        },
        ...currentSessions,
      ];
    sessionsRef.current = nextSessions;
    setSessions(nextSessions);
  }, [currentUsage.input_tokens, currentUsage.output_tokens]);

  const getSessionActiveRun = useCallback((sessionId: string): SessionActiveRun | null => {
    return sessionsRef.current.find((session) => session.id === sessionId)?.active_run || null;
  }, []);

  const getTrackedRunId = useCallback((sessionId: string): string | null => {
    const activeRun = getSessionActiveRun(sessionId);
    if (activeRun?.run_id) {
      return activeRun.run_id;
    }

    if (currentSessionIdRef.current !== sessionId || messagesSessionIdRef.current !== sessionId) {
      return null;
    }

    const pendingMessage = [...messagesRef.current].reverse().find((message) =>
      message.metadata?.run?.id && message.metadata.run.status === 'pending'
    );
    return pendingMessage?.metadata?.run?.id || null;
  }, [getSessionActiveRun]);

  const refreshSessionInfo = useCallback(async (sessionId: string): Promise<Session | null> => {
    try {
      const result: any = await call('get_session', { session_id: sessionId });
      if (result?.status === 'error' || !result?.id) {
        return null;
      }
      const nextSession = result as Session;
      replaceSession(nextSession);
      return nextSession;
    } catch (error) {
      console.error('Failed to get session:', error);
      return null;
    }
  }, [call, replaceSession]);

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
    const trackedRunId = getTrackedRunId(sessionId);
    if (!trackedRunId) {
      return false;
    }

    const snapshot = getTerminalRunSnapshot(candidateMessages, trackedRunId);
    if (!snapshot) {
      return false;
    }

    if (currentSessionIdRef.current === sessionId) {
      messagesRef.current = candidateMessages;
      setMessages(candidateMessages);
      setCurrentUsage((prev) => ({
        input_tokens: prev.input_tokens + (snapshot.usage.input_tokens || 0),
        output_tokens: prev.output_tokens + (snapshot.usage.output_tokens || 0),
        total_tokens: prev.total_tokens + (snapshot.usage.total_tokens || 0),
      }));
    }

    patchSession(sessionId, { active_run: null });
    clearToolActivities();
    refreshSessions().catch((error) => {
      console.error('Failed to refresh sessions after run reconciliation:', error);
    });
    return true;
  }, [clearToolActivities, getTerminalRunSnapshot, getTrackedRunId, patchSession, refreshSessions]);

  const mergePendingAssistantPlaceholder = useCallback((candidateMessages: Message[], sessionId: string): Message[] => {
    const trackedRunId = getTrackedRunId(sessionId);
    if (!trackedRunId) {
      return candidateMessages;
    }

    if (getTerminalRunSnapshot(candidateMessages, trackedRunId)) {
      return candidateMessages;
    }

    const hasPendingAssistant = candidateMessages.some((message) =>
      message.role === 'assistant' &&
      message.metadata?.run?.id === trackedRunId &&
      message.metadata?.run?.status === 'pending'
    );
    if (hasPendingAssistant) {
      return candidateMessages;
    }

    const existingPlaceholder = messagesRef.current.find((message) =>
      message.role === 'assistant' &&
      message.metadata?.run?.id === trackedRunId &&
      message.metadata?.run?.status === 'pending'
    );

    if (!existingPlaceholder) {
      const pendingPlaceholder: Message = {
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString(),
        metadata: {
          run: {
            id: trackedRunId,
            status: 'pending',
          },
        },
      };

      return [
        ...candidateMessages,
        pendingPlaceholder,
      ];
    }

    return [...candidateMessages, existingPlaceholder];
  }, [getTerminalRunSnapshot, getTrackedRunId]);

  const switchSession = useCallback(async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    currentSessionIdRef.current = sessionId;
    setOlderMessagesCursor(null);
    try {
      const sessionInfo = await refreshSessionInfo(sessionId);
      if (currentSessionIdRef.current !== sessionId) {
        return;
      }

      const res: any = await call('list_messages', { session_id: sessionId, limit: MESSAGE_PAGE_SIZE });
      if (currentSessionIdRef.current !== sessionId) {
        return;
      }

      const nextMessages = mergePendingAssistantPlaceholder(res.messages || [], sessionId);
      messagesSessionIdRef.current = sessionId;
      setMessages(nextMessages);
      setOlderMessagesCursor(res.next_cursor || null);
      const reconciledActiveRun = reconcileActiveRunFromMessages(nextMessages, sessionId);
      if (!reconciledActiveRun) {
        messagesRef.current = nextMessages;
      }

      const usageSessionInfo = sessionInfo || sessionsRef.current.find((session) => session.id === sessionId);
      if (usageSessionInfo) {
        setCurrentUsage({
          input_tokens: usageSessionInfo.input_tokens,
          output_tokens: usageSessionInfo.output_tokens,
          total_tokens: usageSessionInfo.input_tokens + usageSessionInfo.output_tokens,
        });
      } else if (!reconciledActiveRun) {
        setCurrentUsage({ input_tokens: 0, output_tokens: 0, total_tokens: 0 });
      }
    } catch (error) {
      console.error('Failed to load session messages:', error);
    }
  }, [call, mergePendingAssistantPlaceholder, reconcileActiveRunFromMessages, refreshSessionInfo]);

  const refreshCurrentSession = useCallback(async () => {
    const sessionId = currentSessionIdRef.current;
    if (!sessionId) {
      return;
    }

    try {
      const sessionInfo = await refreshSessionInfo(sessionId);
      if (currentSessionIdRef.current !== sessionId) {
        return;
      }

      const res: any = await call('list_messages', { session_id: sessionId, limit: MESSAGE_PAGE_SIZE });
      if (currentSessionIdRef.current !== sessionId) {
        return;
      }

      const nextMessages = mergePendingAssistantPlaceholder(res.messages || [], sessionId);
      messagesSessionIdRef.current = sessionId;
      setMessages(nextMessages);
      setOlderMessagesCursor(res.next_cursor || null);

      const reconciledActiveRun = reconcileActiveRunFromMessages(nextMessages, sessionId);
      if (reconciledActiveRun) {
        return;
      }
      messagesRef.current = nextMessages;

      const usageSessionInfo = sessionInfo || sessionsRef.current.find((session) => session.id === sessionId);
      if (usageSessionInfo) {
        setCurrentUsage({
          input_tokens: usageSessionInfo.input_tokens,
          output_tokens: usageSessionInfo.output_tokens,
          total_tokens: usageSessionInfo.input_tokens + usageSessionInfo.output_tokens,
        });
      }
    } catch (error) {
      console.error('Failed to refresh current session messages:', error);
    }
  }, [call, mergePendingAssistantPlaceholder, reconcileActiveRunFromMessages, refreshSessionInfo]);

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

    const refreshedSessionId = lastEvent.session_id || payload.entity_id;
    if (refreshedSessionId && getTrackedRunId(refreshedSessionId)) {
      return;
    }

    refreshSessions().catch((error) => {
      console.error('Failed to refresh sessions after session event:', error);
    });
  }, [getTrackedRunId, lastEvent, refreshSessions]);

  useEffect(() => {
    if (!lastEvent || lastEvent.namespace !== 'agent' || lastEvent.event !== 'chat_final') {
      return;
    }

    const payload = lastEvent.payload as any;
    const eventSessionId = lastEvent.session_id || '';
    const activeRun = eventSessionId ? getSessionActiveRun(eventSessionId) : null;
    if (!eventSessionId || !activeRun || payload?.run_id !== activeRun.run_id) {
      return;
    }

    const usage = payload?.usage || { input_tokens: 0, output_tokens: 0, total_tokens: 0 };
    const responseMessages = Array.isArray(payload?.messages) ? payload.messages : [];
    const latestAssistantMessage = [...responseMessages].reverse().find((message: any) => message.role === 'assistant');
    const latestAssistantResponse = latestAssistantMessage?.content || '';
    const runMetadata = latestAssistantMessage?.metadata?.run || {};
    const runStatus: MessageRunStatus = runMetadata.status || (latestAssistantResponse.startsWith('Run failed:') ? 'failed' : 'success');
    const nextRunMetadata: MessageRunMetadata = {
      id: runMetadata.id || activeRun.run_id,
      status: runStatus,
      ...(runMetadata.error ? { error: runMetadata.error } : {}),
    };
    const isVisibleRunSession = currentSessionId === eventSessionId;

    if (isVisibleRunSession) {
      setMessages((prev) => {
        if (runStatus === 'canceled') {
          return prev
            .filter((message) => !(
              message.role === 'assistant' &&
              message.metadata?.run?.id === activeRun.run_id &&
              message.metadata?.run?.status === 'pending'
            ))
            .map((message) => (
              message.role === 'user' && message.metadata?.run?.id === activeRun.run_id
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
          if (message.role === 'user' && message.metadata?.run?.id === activeRun.run_id) {
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
            message.metadata?.run?.id === activeRun.run_id &&
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

    patchSession(eventSessionId, { active_run: null });
    clearToolActivities();
    refreshSessions().catch((error) => {
      console.error('Failed to refresh sessions after chat final event:', error);
    });
  }, [clearToolActivities, currentSessionId, getSessionActiveRun, lastEvent, patchSession, refreshSessions]);

  useEffect(() => {
    if (!lastEvent || lastEvent.namespace !== 'data' || lastEvent.event !== 'refresh') {
      return;
    }

    const payload = lastEvent.payload as RefreshPayload;
    const refreshedSessionId = lastEvent.session_id || payload.entity_id;
    if (payload.entity !== 'session' || !refreshedSessionId || !getTrackedRunId(refreshedSessionId)) {
      return;
    }

    let cancelled = false;

    call('list_messages', { session_id: refreshedSessionId, limit: MESSAGE_PAGE_SIZE })
      .then((res: any) => {
        if (cancelled) {
          return;
        }

        reconcileActiveRunFromMessages(
          mergePendingAssistantPlaceholder(res.messages || [], refreshedSessionId),
          refreshedSessionId
        );
      })
      .catch((error) => {
        console.error('Failed to reconcile active run from session refresh:', error);
      });

    return () => {
      cancelled = true;
    };
  }, [call, getTrackedRunId, lastEvent, mergePendingAssistantPlaceholder, reconcileActiveRunFromMessages]);

  const createNewSession = useCallback(async () => {
    try {
      const res: any = await call('create_session', {});
      const newId = String(res?.id || '').trim();
      if (!newId) {
        throw new Error('Backend did not return a session id');
      }
      setCurrentSessionId(newId);
      currentSessionIdRef.current = newId;
      messagesSessionIdRef.current = newId;
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
    const targetSessionId = currentSessionId;
    if (!targetSessionId) {
      return { status: 'error', message: translateStatic('chat.run_failed') };
    }
    if (getSessionActiveRun(targetSessionId) || isSubmitting) {
      return { status: 'busy', message: translateStatic('chat.session_busy') };
    }
    setIsSubmitting(true);
    messagesSessionIdRef.current = targetSessionId;

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
      messagesSessionIdRef.current = targetSessionId;
      const localPendingMessages: Message[] = [
        ...messagesRef.current,
        {
          role: 'user',
          content: trimmedInstruction,
          created_at: nowIso,
          metadata: {
            run: {
              id: runId,
              status: 'pending',
            },
          },
        },
        {
          role: 'assistant',
          content: '',
          created_at: nowIso,
          metadata: { run: { id: runId, status: 'pending' } },
        },
      ];
      messagesRef.current = localPendingMessages;
      setMessages(localPendingMessages);
      patchSession(targetSessionId, {
        active_run: {
          run_id: runId,
          status: 'running',
          started_at: nowIso,
        },
      });
      return { status: 'started', runId };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { status: 'error', message };
    } finally {
      setIsSubmitting(false);
    }
  }, [clearToolActivities, currentSessionId, executeInstruction, getSessionActiveRun, isSubmitting, patchSession]);

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
    const sessionId = currentSessionIdRef.current;
    const runToStop = sessionId ? getSessionActiveRun(sessionId) : null;
    if (!runToStop) return;

    setMessages((prev) => prev
      .filter((message) => !(
        message.role === 'assistant' &&
        message.metadata?.run?.id === runToStop.run_id &&
        message.metadata?.run?.status === 'pending'
      ))
      .map((message) => (
        message.role === 'user' && message.metadata?.run?.id === runToStop.run_id
          ? {
              ...message,
              metadata: {
                ...(message.metadata || {}),
                run: {
                  ...(message.metadata?.run || {}),
                  id: runToStop.run_id,
                  status: 'canceled',
                },
              },
            }
          : message
      )));

    patchSession(sessionId, { active_run: null });
    clearToolActivities();

    try {
      await cancelRun(runToStop.run_id, sessionId);
    } catch (error) {
      console.error('Failed to cancel active run:', error);
    }
  }, [cancelRun, clearToolActivities, getSessionActiveRun, patchSession]);

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
    refreshCurrentSession,
    switchSession,
    createNewSession,
    deleteSession,
    loadOlderMessages,
    execute,
    stopActiveRun,
    hasOlderMessages: olderMessagesCursor !== null,
    isLoadingOlderMessages,
    isSubmitting,
    isExecuting: Boolean(getSessionActiveRun(currentSessionId)),
  };
}
