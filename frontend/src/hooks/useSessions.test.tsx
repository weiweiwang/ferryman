import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { FerrymanEvent } from './useBackendConnection';
import { useSessions, type ExecuteResult } from './useSessions';

describe('useSessions', () => {
  beforeEach(() => {
    const storage = new Map<string, string>();
    const localStorageMock = {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => {
        storage.set(key, String(value));
      }),
      removeItem: vi.fn((key: string) => {
        storage.delete(key);
      }),
      clear: vi.fn(() => {
        storage.clear();
      }),
    };

    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: localStorageMock,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('optimistically cancels the active run before the backend final event arrives', async () => {
    const call = vi.fn().mockResolvedValue({ sessions: [] });
    const executeInstruction = vi.fn().mockResolvedValue({ status: 'started', run_id: 'run-optimistic-cancel-1' });
    const cancelRun = vi.fn().mockResolvedValue({ status: 'canceling' });
    const clearToolActivities = vi.fn();

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent: null,
      })
    );

    await act(async () => {
      await result.current.switchSession('session-1');
    });

    await act(async () => {
      await result.current.execute('Stop this immediately');
    });

    expect(result.current.isExecuting).toBe(true);
    expect(result.current.messages).toHaveLength(2);

    await act(async () => {
      await result.current.stopActiveRun();
    });

    expect(cancelRun).toHaveBeenCalledWith('run-optimistic-cancel-1', 'session-1');
    expect(result.current.isExecuting).toBe(false);
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: 'user',
      content: 'Stop this immediately',
      metadata: {
        run: {
          id: 'run-optimistic-cancel-1',
          status: 'canceled',
        },
      },
    });
    expect(clearToolActivities).toHaveBeenCalledTimes(2);
  });

  it('removes the pending assistant bubble and marks the user message as canceled', async () => {
    const call = vi.fn().mockResolvedValue({ sessions: [] });
    const executeInstruction = vi.fn().mockResolvedValue({ status: 'started', run_id: 'run-cancel-1' });
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();
    let lastEvent: FerrymanEvent | null = null;

    const { result, rerender } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent,
      })
    );

    await act(async () => {
      await result.current.switchSession('session-1');
    });

    await act(async () => {
      await result.current.execute('Please cancel this run');
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].role).toBe('user');
    expect(result.current.messages[0].metadata?.run).toMatchObject({
      id: 'run-cancel-1',
      status: 'pending',
    });
    expect(result.current.messages[1].role).toBe('assistant');
    expect(result.current.messages[1].metadata?.run?.status).toBe('pending');

    lastEvent = {
      namespace: 'agent',
      event: 'chat_final',
      session_id: 'session-1',
      ts: '2026-04-15T14:30:00Z',
      payload: {
        run_id: 'run-cancel-1',
        messages: [
          {
            role: 'assistant',
            content: 'Run canceled.',
            metadata: {
              run: {
                id: 'run-cancel-1',
                status: 'canceled',
              },
            },
          },
        ],
        usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
      },
    };
    rerender();

    await waitFor(() => {
      expect(result.current.isExecuting).toBe(false);
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]).toMatchObject({
      role: 'user',
      content: 'Please cancel this run',
      metadata: {
        run: {
          id: 'run-cancel-1',
          status: 'canceled',
        },
      },
    });
    expect(clearToolActivities).toHaveBeenCalledTimes(2);
  });

  it('keeps the assistant message for successful runs and updates usage', async () => {
    const call = vi.fn().mockResolvedValue({ sessions: [] });
    const executeInstruction = vi.fn().mockResolvedValue({ status: 'started', run_id: 'run-success-1' });
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();
    let lastEvent: FerrymanEvent | null = null;

    const { result, rerender } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent,
      })
    );

    await act(async () => {
      await result.current.switchSession('session-1');
    });

    await act(async () => {
      await result.current.execute('Finish this run');
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].id).toBeUndefined();
    expect(result.current.messages[1].id).toBeUndefined();

    lastEvent = {
      namespace: 'agent',
      event: 'chat_final',
      session_id: 'session-1',
      ts: '2026-04-15T14:35:00Z',
      payload: {
        run_id: 'run-success-1',
        messages: [
          {
            role: 'assistant',
            content: 'Completed successfully.',
            metadata: {
              run: {
                id: 'run-success-1',
                status: 'success',
              },
              model: {
                name: 'test-model',
                provider: 'test-provider',
              },
              usage: {
                version: 1,
                request: {
                  total: { input_tokens: 12, output_tokens: 8, total_tokens: 20 },
                  by_model: {
                    'test-provider:test-model': {
                      input_tokens: 12,
                      output_tokens: 8,
                      total_tokens: 20,
                      request_count: 1,
                    },
                  },
                },
                classifier: {
                  model: 'gemini:gemini-3.1-flash-lite-preview',
                  input_tokens: 2,
                  output_tokens: 1,
                  total_tokens: 3,
                  request_count: 1,
                },
              },
              cost: {
                version: 1,
                currency: 'USD',
                complete: true,
                estimated: true,
                total: { input_cost: 0.01, output_cost: 0.02, total_cost: 0.03 },
                missing_pricing: [],
              },
            },
          },
        ],
        usage: { input_tokens: 12, output_tokens: 8, total_tokens: 20 },
      },
    };
    rerender();

    await waitFor(() => {
      expect(result.current.isExecuting).toBe(false);
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].metadata?.run).toMatchObject({
      id: 'run-success-1',
      status: 'success',
    });
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      content: 'Completed successfully.',
      metadata: {
        run: {
          id: 'run-success-1',
          status: 'success',
        },
        model: {
          name: 'test-model',
          provider: 'test-provider',
        },
        usage: {
          version: 1,
          request: {
            total: { input_tokens: 12, output_tokens: 8, total_tokens: 20 },
            by_model: {
              'test-provider:test-model': {
                input_tokens: 12,
                output_tokens: 8,
                total_tokens: 20,
                request_count: 1,
              },
            },
          },
          classifier: {
            model: 'gemini:gemini-3.1-flash-lite-preview',
            input_tokens: 2,
            output_tokens: 1,
            total_tokens: 3,
            request_count: 1,
          },
        },
        cost: {
          version: 1,
          currency: 'USD',
          complete: true,
          estimated: true,
          total: { input_cost: 0.01, output_cost: 0.02, total_cost: 0.03 },
          missing_pricing: [],
        },
      },
    });
    expect(result.current.currentUsage).toEqual({
      input_tokens: 12,
      output_tokens: 8,
      total_tokens: 20,
    });
  });

  it('does not insert local messages when execute is rejected as busy', async () => {
    const call = vi.fn().mockResolvedValue({ sessions: [] });
    const executeInstruction = vi.fn().mockResolvedValue({
      status: 'busy',
      run_id: 'run-existing-1',
      message: 'Current session already has an active run.',
    });
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();
    const lastEvent: FerrymanEvent | null = null;

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent,
      })
    );

    await act(async () => {
      await result.current.switchSession('session-1');
    });

    let executeResult: ExecuteResult | undefined;
    await act(async () => {
      executeResult = await result.current.execute('Do not enqueue this');
    });

    expect(executeResult).toEqual({
      status: 'busy',
      message: 'Current session already has an active run.',
      runId: 'run-existing-1',
    });
    expect(result.current.messages).toEqual([]);
    expect(result.current.isExecuting).toBe(false);
    expect(result.current.isSubmitting).toBe(false);
    expect(clearToolActivities).not.toHaveBeenCalled();
  });

  it('allows a second session to submit while another session is running', async () => {
    const call = vi.fn(async (method: string, params?: any) => {
      if (method === 'get_session') {
        return {
          id: params.session_id,
          title: params.session_id,
          updated_at: '2026-04-15T14:00:00Z',
          input_tokens: 0,
          output_tokens: 0,
          active_run: null,
        };
      }
      if (method === 'list_messages') {
        return { messages: [] };
      }
      if (method === 'list_sessions') {
        return { sessions: [] };
      }
      return {};
    });
    const executeInstruction = vi.fn()
      .mockResolvedValueOnce({ status: 'started', run_id: 'run-session-a' })
      .mockResolvedValueOnce({ status: 'started', run_id: 'run-session-b' });
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent: null,
      })
    );

    await act(async () => {
      await result.current.switchSession('session-a');
    });

    await act(async () => {
      await result.current.execute('Run in session A');
    });

    expect(result.current.isExecuting).toBe(true);

    await act(async () => {
      await result.current.switchSession('session-b');
    });

    expect(result.current.isExecuting).toBe(false);

    await act(async () => {
      await result.current.execute('Run in session B');
    });

    expect(executeInstruction).toHaveBeenNthCalledWith(1, 'Run in session A', 'session-a');
    expect(executeInstruction).toHaveBeenNthCalledWith(2, 'Run in session B', 'session-b');
    expect(cancelRun).not.toHaveBeenCalled();
    expect(result.current.isExecuting).toBe(true);
  });

  it('reconciles a finished run from persisted messages when the final event is missed', async () => {
    const persistedMessages = [
      {
        id: 'user-server-1',
        role: 'user' as const,
        content: 'Recover from storage',
        created_at: '2026-04-15T14:41:00Z',
        metadata: {
          run: {
            id: 'run-reconcile-1',
            status: 'success' as const,
          },
        },
      },
      {
        id: 'assistant-server-1',
        role: 'assistant' as const,
        content: 'Recovered final answer.',
        created_at: '2026-04-15T14:41:05Z',
        metadata: {
          run: {
            id: 'run-reconcile-1',
            status: 'success' as const,
          },
          usage: {
            input_tokens: 9,
            output_tokens: 6,
            total_tokens: 15,
          },
        },
      },
    ];
    let listMessagesCount = 0;
    const call = vi.fn(async (method: string, params?: any) => {
      if (method === 'get_session') {
        return {
          id: params.session_id,
          title: 'Session 1',
          updated_at: '2026-04-15T14:41:00Z',
          input_tokens: 0,
          output_tokens: 0,
          active_run: null,
        };
      }
      if (method === 'list_sessions') {
        return { sessions: [] };
      }
      if (method === 'list_messages') {
        listMessagesCount += 1;
        return { messages: listMessagesCount === 1 ? [] : persistedMessages };
      }
      return {};
    });
    const executeInstruction = vi.fn().mockResolvedValue({ status: 'started', run_id: 'run-reconcile-1' });
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();
    let lastEvent: FerrymanEvent | null = null;

    const { result, rerender } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent,
      })
    );

    await act(async () => {
      await result.current.switchSession('session-1');
    });

    await act(async () => {
      await result.current.execute('Recover from storage');
    });

    expect(result.current.isExecuting).toBe(true);
    expect(result.current.messages).toHaveLength(2);

    lastEvent = {
      namespace: 'data',
      event: 'refresh',
      session_id: 'session-1',
      ts: '2026-04-15T14:41:10Z',
      payload: {
        entity: 'session',
        action: 'updated',
        entity_id: 'session-1',
      },
    };
    rerender();

    await waitFor(() => {
      expect(result.current.isExecuting).toBe(false);
    });

    expect(result.current.messages).toEqual(persistedMessages);
    expect(result.current.currentUsage).toEqual({
      input_tokens: 9,
      output_tokens: 6,
      total_tokens: 15,
    });
    expect(clearToolActivities).toHaveBeenCalledTimes(2);
  });

  it('refreshes the current session when the window regains focus after a missed final event', async () => {
    const persistedMessages = [
      {
        id: 'user-server-focus-1',
        role: 'user' as const,
        content: 'Recover on focus',
        created_at: '2026-04-15T14:51:00Z',
        metadata: {
          run: {
            id: 'run-focus-reconcile-1',
            status: 'success' as const,
          },
        },
      },
      {
        id: 'assistant-server-focus-1',
        role: 'assistant' as const,
        content: 'Recovered after focus.',
        created_at: '2026-04-15T14:51:04Z',
        metadata: {
          run: {
            id: 'run-focus-reconcile-1',
            status: 'success' as const,
          },
          usage: {
            input_tokens: 4,
            output_tokens: 11,
            total_tokens: 15,
          },
        },
      },
    ];
    let listMessagesCount = 0;
    let finalRunPersisted = false;
    const call = vi.fn(async (method: string, params?: any) => {
      if (method === 'get_session') {
        return {
          id: params.session_id,
          title: 'Session 1',
          updated_at: '2026-04-15T14:50:00Z',
          input_tokens: finalRunPersisted ? 4 : 0,
          output_tokens: finalRunPersisted ? 11 : 0,
          active_run: null,
        };
      }
      if (method === 'list_sessions') {
        return {
          sessions: [{
            id: 'session-1',
            title: 'Session 1',
            updated_at: '2026-04-15T14:50:00Z',
            input_tokens: 0,
            output_tokens: 0,
          }],
        };
      }
      if (method === 'list_messages') {
        listMessagesCount += 1;
        return { messages: listMessagesCount === 1 ? [] : persistedMessages };
      }
      return {};
    });
    const executeInstruction = vi.fn().mockResolvedValue({ status: 'started', run_id: 'run-focus-reconcile-1' });
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();
    const lastEvent: FerrymanEvent | null = null;

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent,
        isConnected: true,
      })
    );

    await waitFor(() => {
      expect(call).toHaveBeenCalledWith('list_messages', { session_id: 'session-1', limit: 20 });
    });

    await act(async () => {
      await result.current.execute('Recover on focus');
    });

    expect(result.current.isExecuting).toBe(true);
    expect(result.current.messages).toHaveLength(2);

    finalRunPersisted = true;
    act(() => {
      result.current.refreshCurrentSession();
    });

    await waitFor(() => {
      expect(result.current.isExecuting).toBe(false);
    });

    expect(result.current.messages).toEqual(persistedMessages);
    expect(result.current.currentUsage).toEqual({
      input_tokens: 4,
      output_tokens: 11,
      total_tokens: 15,
    });
    expect(clearToolActivities).toHaveBeenCalledTimes(2);
  });

  it('preserves the pending assistant bubble when the window regains focus mid-run', async () => {
    const persistedPendingMessages = [
      {
        id: 'user-server-pending-1',
        role: 'user' as const,
        content: 'Keep thinking after focus',
        created_at: '2026-04-15T14:56:00Z',
        metadata: {
          run: {
            id: 'run-focus-pending-1',
            status: 'pending' as const,
          },
        },
      },
    ];
    let listMessagesCount = 0;
    let hasStartedPendingRun = false;
    const call = vi.fn(async (method: string, params?: any) => {
      if (method === 'get_session') {
        return {
          id: params.session_id,
          title: 'Session 1',
          updated_at: '2026-04-15T14:55:00Z',
          input_tokens: 0,
          output_tokens: 0,
          active_run: hasStartedPendingRun ? {
            run_id: 'run-focus-pending-1',
            status: 'running',
            started_at: '2026-04-15T14:56:00Z',
          } : null,
        };
      }
      if (method === 'list_sessions') {
        return {
          sessions: [{
            id: 'session-1',
            title: 'Session 1',
            updated_at: '2026-04-15T14:55:00Z',
            input_tokens: 0,
            output_tokens: 0,
          }],
        };
      }
      if (method === 'list_messages') {
        listMessagesCount += 1;
        return { messages: listMessagesCount === 1 ? [] : persistedPendingMessages };
      }
      return {};
    });
    const executeInstruction = vi.fn().mockResolvedValue({ status: 'started', run_id: 'run-focus-pending-1' });
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();
    const lastEvent: FerrymanEvent | null = null;

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent,
        isConnected: true,
      })
    );

    await waitFor(() => {
      expect(call).toHaveBeenCalledWith('list_messages', { session_id: 'session-1', limit: 20 });
    });

    await act(async () => {
      await result.current.execute('Keep thinking after focus');
    });
    hasStartedPendingRun = true;

    expect(result.current.isExecuting).toBe(true);
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      metadata: {
        run: {
          id: 'run-focus-pending-1',
          status: 'pending',
        },
      },
    });

    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(() => {
      expect(result.current.messages[0].id).toBe('user-server-pending-1');
    });

    expect(result.current.isExecuting).toBe(true);
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      metadata: {
        run: {
          id: 'run-focus-pending-1',
          status: 'pending',
        },
      },
    });
    expect(clearToolActivities).toHaveBeenCalledTimes(1);
  });

  it('does not overwrite the currently viewed session when another session run finishes', async () => {
    const sessionTwoMessages = [
      {
        id: 'session-2-message',
        role: 'assistant' as const,
        content: 'Session 2 stays visible.',
        created_at: '2026-04-15T14:40:00Z',
      },
    ];
    const call = vi.fn(async (method: string, params?: any) => {
      if (method === 'list_messages' && params?.session_id === 'session-2') {
        return { messages: sessionTwoMessages };
      }
      if (method === 'list_sessions') {
        return {
          sessions: [
            {
              id: 'session-1',
              title: 'session-1',
              updated_at: '2026-04-15T14:00:00Z',
              input_tokens: 0,
              output_tokens: 0,
            },
            {
              id: 'session-2',
              title: 'Session 2',
              updated_at: '2026-04-15T14:40:00Z',
              input_tokens: 0,
              output_tokens: 0,
            },
          ],
        };
      }
      return {};
    });
    const executeInstruction = vi.fn().mockResolvedValue({ status: 'started', run_id: 'run-cross-session-1' });
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();
    let lastEvent: FerrymanEvent | null = null;

    const { result, rerender } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent,
      })
    );

    await act(async () => {
      await result.current.switchSession('session-1');
    });

    await act(async () => {
      await result.current.execute('Finish in the session-1 session');
    });

    await act(async () => {
      await result.current.switchSession('session-2');
    });

    expect(result.current.currentSessionId).toBe('session-2');
    expect(result.current.messages).toEqual(sessionTwoMessages);

    lastEvent = {
      namespace: 'agent',
      event: 'chat_final',
      session_id: 'session-1',
      ts: '2026-04-15T14:45:00Z',
      payload: {
        run_id: 'run-cross-session-1',
        messages: [
          {
            role: 'assistant',
            content: 'session-1 session finished.',
            metadata: {
              run: {
                id: 'run-cross-session-1',
                status: 'success',
              },
            },
          },
        ],
        usage: { input_tokens: 5, output_tokens: 7, total_tokens: 12 },
      },
    };
    rerender();

    await waitFor(() => {
      expect(result.current.isExecuting).toBe(false);
    });

    expect(result.current.currentSessionId).toBe('session-2');
    expect(result.current.messages).toEqual(sessionTwoMessages);
    expect(result.current.currentUsage).toEqual({
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
    });
  });

  it('loads the latest 20 messages first and prepends older messages with the cursor', async () => {
    const latestMessages = [
      {
        id: 'message-21',
        role: 'user' as const,
        content: 'Latest page start',
        created_at: '2026-04-15T14:21:00Z',
      },
      {
        id: 'message-40',
        role: 'assistant' as const,
        content: 'Latest page end',
        created_at: '2026-04-15T14:40:00Z',
      },
    ];
    const olderMessages = [
      {
        id: 'message-1',
        role: 'user' as const,
        content: 'Older page start',
        created_at: '2026-04-15T14:01:00Z',
      },
      {
        id: 'message-20',
        role: 'assistant' as const,
        content: 'Older page end',
        created_at: '2026-04-15T14:20:00Z',
      },
    ];
    const call = vi.fn(async (method: string, params?: any) => {
      if (method === 'list_messages' && params?.cursor === 'older-cursor-1') {
        return { messages: olderMessages, next_cursor: null };
      }
      if (method === 'list_messages') {
        return { messages: latestMessages, next_cursor: 'older-cursor-1' };
      }
      if (method === 'list_sessions') {
        return { sessions: [] };
      }
      return {};
    });
    const executeInstruction = vi.fn();
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent: null,
      })
    );

    await act(async () => {
      await result.current.switchSession('session-paged');
    });

    expect(call).toHaveBeenCalledWith('list_messages', { session_id: 'session-paged', limit: 20 });
    expect(result.current.messages).toEqual(latestMessages);
    expect(result.current.hasOlderMessages).toBe(true);

    await act(async () => {
      await result.current.loadOlderMessages();
    });

    expect(call).toHaveBeenCalledWith('list_messages', {
      session_id: 'session-paged',
      limit: 20,
      cursor: 'older-cursor-1',
    });
    expect(result.current.messages).toEqual([...olderMessages, ...latestMessages]);
    expect(result.current.hasOlderMessages).toBe(false);
  });

  it('creates new chat sessions using the backend returned id', async () => {
    const call = vi.fn(async (method: string) => {
      if (method === 'create_session') {
        return { id: 'backend-shortuuid-1', title: '' };
      }
      if (method === 'list_sessions') {
        return {
          sessions: [
            {
              id: 'backend-shortuuid-1',
              title: '',
              updated_at: '2026-04-15T14:00:00Z',
              input_tokens: 0,
              output_tokens: 0,
            },
          ],
        };
      }
      return {};
    });
    const executeInstruction = vi.fn();
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent: null,
      })
    );

    await act(async () => {
      await result.current.createNewSession();
    });

    expect(call).toHaveBeenCalledWith('create_session', {});
    expect(result.current.currentSessionId).toBe('backend-shortuuid-1');
  });

  it('renames sessions using the backend returned session payload', async () => {
    const call = vi.fn(async (method: string, params?: any) => {
      if (method === 'list_sessions') {
        return {
          sessions: [
            {
              id: 'session-1',
              title: 'Original Session',
              updated_at: '2026-04-15T14:00:00Z',
              input_tokens: 2,
              output_tokens: 3,
              active_run: null,
            },
          ],
        };
      }
      if (method === 'update_session') {
        return {
          id: params.session_id,
          title: params.title,
          updated_at: '2026-04-15T14:05:00Z',
          input_tokens: 2,
          output_tokens: 3,
          active_run: null,
        };
      }
      return {};
    });
    const executeInstruction = vi.fn();
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent: null,
      })
    );

    await act(async () => {
      await result.current.refreshSessions();
    });

    await act(async () => {
      await result.current.renameSession('session-1', '  Renamed Session  ');
    });

    expect(call).toHaveBeenCalledWith('update_session', {
      session_id: 'session-1',
      title: 'Renamed Session',
    });
    expect(result.current.sessions[0]).toMatchObject({
      id: 'session-1',
      title: 'Renamed Session',
      updated_at: '2026-04-15T14:05:00Z',
    });
  });

  it('bootstraps an empty client by creating a backend session', async () => {
    const call = vi.fn(async (method: string) => {
      if (method === 'list_sessions') {
        return { sessions: [] };
      }
      if (method === 'create_session') {
        return { id: 'bootstrap-shortuuid-1', title: '' };
      }
      return {};
    });
    const executeInstruction = vi.fn();
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent: null,
        isConnected: true,
      })
    );

    await waitFor(() => {
      expect(result.current.currentSessionId).toBe('bootstrap-shortuuid-1');
    });
    expect(call).toHaveBeenCalledWith('create_session', {});
  });

  it('bootstraps the most recently updated session from the session list', async () => {
    const recentMessages = [
      {
        id: 'recent-message-1',
        role: 'assistant' as const,
        content: 'Recent session loaded.',
        created_at: '2026-04-15T15:01:00Z',
      },
    ];
    const call = vi.fn(async (method: string, params?: any) => {
      if (method === 'list_sessions') {
        return {
          sessions: [
            {
              id: 'recent-session',
              title: 'Recent Session',
              updated_at: '2026-04-15T15:02:00Z',
              input_tokens: 2,
              output_tokens: 3,
            },
            {
              id: 'older-session',
              title: 'Older Session',
              updated_at: '2026-04-15T14:00:00Z',
              input_tokens: 0,
              output_tokens: 0,
            },
          ],
        };
      }
      if (method === 'list_messages' && params?.session_id === 'recent-session') {
        return { messages: recentMessages };
      }
      return {};
    });
    const executeInstruction = vi.fn();
    const cancelRun = vi.fn();
    const clearToolActivities = vi.fn();

    const { result } = renderHook(() =>
      useSessions({
        call,
        executeInstruction,
        cancelRun,
        clearToolActivities,
        lastEvent: null,
        isConnected: true,
      })
    );

    await waitFor(() => {
      expect(result.current.currentSessionId).toBe('recent-session');
      expect(result.current.messages).toEqual(recentMessages);
    });

    expect(call).toHaveBeenCalledWith('list_sessions', { limit: 50 });
    expect(result.current.currentUsage).toEqual({
      input_tokens: 2,
      output_tokens: 3,
      total_tokens: 5,
    });
  });
});
