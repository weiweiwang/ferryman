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
      await result.current.execute('Please cancel this run');
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].role).toBe('user');
    expect(result.current.messages[0].metadata?.run).toMatchObject({
      id: 'run-cancel-1',
      status: 'pending',
      scope: 'master',
    });
    expect(result.current.messages[1].role).toBe('assistant');
    expect(result.current.messages[1].metadata?.run?.status).toBe('pending');

    lastEvent = {
      namespace: 'agent',
      event: 'chat_final',
      session_id: 'default',
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
                scope: 'master',
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
          scope: 'master',
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
      await result.current.execute('Finish this run');
    });

    lastEvent = {
      namespace: 'agent',
      event: 'chat_final',
      session_id: 'default',
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
                scope: 'master',
              },
              model: {
                name: 'test-model',
                provider: 'test-provider',
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
      scope: 'master',
    });
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      content: 'Completed successfully.',
      metadata: {
        run: {
          id: 'run-success-1',
          status: 'success',
          scope: 'master',
        },
        usage: {
          input_tokens: 12,
          output_tokens: 8,
          total_tokens: 20,
        },
        model: {
          name: 'test-model',
          provider: 'test-provider',
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
            scope: 'master',
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
            scope: 'master',
          },
          usage: {
            input_tokens: 9,
            output_tokens: 6,
            total_tokens: 15,
          },
        },
      },
    ];
    const call = vi.fn(async (method: string) => {
      if (method === 'list_sessions') {
        return { sessions: [] };
      }
      if (method === 'list_messages') {
        return { messages: persistedMessages };
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
      await result.current.execute('Recover from storage');
    });

    expect(result.current.isExecuting).toBe(true);
    expect(result.current.messages).toHaveLength(2);

    lastEvent = {
      namespace: 'data',
      event: 'refresh',
      session_id: 'default',
      ts: '2026-04-15T14:41:10Z',
      payload: {
        entity: 'session',
        action: 'updated',
        entity_id: 'default',
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
            scope: 'master',
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
            scope: 'master',
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
    const call = vi.fn(async (method: string) => {
      if (method === 'list_sessions') {
        return { sessions: [] };
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
      expect(call).toHaveBeenCalledWith('list_messages', { session_id: 'default', limit: 100 });
    });

    await act(async () => {
      await result.current.execute('Recover on focus');
    });

    expect(result.current.isExecuting).toBe(true);
    expect(result.current.messages).toHaveLength(2);

    await act(async () => {
      window.dispatchEvent(new Event('focus'));
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
              id: 'default',
              title: 'Default',
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
      await result.current.execute('Finish in the default session');
    });

    await act(async () => {
      await result.current.switchSession('session-2');
    });

    expect(result.current.currentSessionId).toBe('session-2');
    expect(result.current.messages).toEqual(sessionTwoMessages);

    lastEvent = {
      namespace: 'agent',
      event: 'chat_final',
      session_id: 'default',
      ts: '2026-04-15T14:45:00Z',
      payload: {
        run_id: 'run-cross-session-1',
        messages: [
          {
            role: 'assistant',
            content: 'Default session finished.',
            metadata: {
              run: {
                id: 'run-cross-session-1',
                status: 'success',
                scope: 'master',
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
});
