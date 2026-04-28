import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { openUrl } from '@tauri-apps/plugin-opener';

import App from './App';
import { useBackendConnection, type ToolActivityPayload } from './hooks/useBackendConnection';
import { useSessions, type Message } from './hooks/useSessions';
import { useI18n } from './hooks/useI18n';

vi.mock('./hooks/useBackendConnection', () => ({
  useBackendConnection: vi.fn(),
}));

vi.mock('./hooks/useSessions', () => ({
  useSessions: vi.fn(),
}));

vi.mock('./hooks/useI18n', () => ({
  useI18n: vi.fn(),
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));

vi.mock('@tauri-apps/plugin-opener', () => ({
  openUrl: vi.fn(),
}));

const mockedUseBackendConnection = vi.mocked(useBackendConnection);
const mockedUseSessions = vi.mocked(useSessions);
const mockedUseI18n = vi.mocked(useI18n);
const mockedOpenUrl = vi.mocked(openUrl);

let mockedMessages: Message[] = [];
let mockedToolActivities: ToolActivityPayload[] = [];
const clipboardWriteText = vi.fn();
const scrollIntoView = vi.fn();

describe('App chat interactions', () => {
  beforeEach(() => {
    mockedMessages = [];
    mockedToolActivities = [];
    clipboardWriteText.mockReset();
    mockedOpenUrl.mockReset();
    scrollIntoView.mockReset();

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

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: clipboardWriteText.mockResolvedValue(undefined),
      },
    });

    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });

    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());

    mockedUseI18n.mockReturnValue({
      locale: 'en',
      changeLanguage: vi.fn(),
      t: (key: string) =>
        (
          {
            'app.title': 'Ferryman',
            'app.subtitle': 'Busywork, handled.',
            'chat.header_title': 'Chat',
            'chat.placeholder': 'Prompt',
            'chat.send_shortcut_enter_hint': 'Enter to send',
            'chat.send_shortcut_mod_enter_hint': 'Send with Cmd/Ctrl + Enter',
            'chat.stop': 'Stop current run',
            'chat.status_canceled': 'Canceled',
            'chat.session_busy': 'This session is still running.',
            'common.copy': 'Copy',
            'common.copied': 'Copied',
            'nav.recent_sessions': 'Recent Sessions',
            'nav.new_chat': 'New Chat',
            'nav.tasks': 'Tasks',
            'nav.schedules': 'Schedules',
            'nav.skills': 'Skills',
            'nav.settings': 'Settings',
            'tasks.tokens_unit': 'Tokens',
            'tasks.token_in': 'IN',
            'tasks.token_out': 'OUT',
            'tasks.token_total': 'TOT',
            'chat.send_mode': 'Send mode',
            'settings.no_models': 'No models',
            'app.byok_enabled': 'BYOK',
            'app.deterministic_kernel': 'Kernel',
          } as Record<string, string>
        )[key] ?? key,
    });

    mockedUseBackendConnection.mockImplementation(() => ({
      call: vi.fn(async (method: string) => {
        if (method === 'get_active_model') {
          return 'qwen:qwen3.6-plus';
        }
        if (method === 'get_model_readiness') {
          return { ready: true, active_model: 'qwen:qwen3.6-plus', issue: null };
        }
        if (method === 'get_llm_configs') {
          return [];
        }
        if (method === 'get_available_models') {
          return {};
        }
        if (method === 'list_skills') {
          return [];
        }
        if (method === 'read_backend_logs') {
          return { content: '' };
        }
        return {};
      }),
      execute: vi.fn(),
      cancelRun: vi.fn(),
      isConnected: true,
      tasks: [],
      toolActivities: mockedToolActivities,
      lastEvent: null,
      refreshTasks: vi.fn(),
      clearToolActivities: vi.fn(),
    }));

    mockedUseSessions.mockImplementation(() => ({
      messages: mockedMessages,
      setMessages: vi.fn(),
      sessions: [
        {
          id: 'session-1',
          title: 'Session 1',
          updated_at: '2026-04-15T00:00:00Z',
          input_tokens: 0,
          output_tokens: 0,
        },
      ],
      currentSessionId: 'session-1',
      currentUsage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
      refreshSessions: vi.fn(),
      switchSession: vi.fn(),
      createNewSession: vi.fn().mockResolvedValue('session-2'),
      deleteSession: vi.fn(),
      loadOlderMessages: vi.fn(),
      execute: vi.fn().mockResolvedValue({ status: 'started' }),
      stopActiveRun: vi.fn(),
      hasOlderMessages: false,
      isLoadingOlderMessages: false,
      isSubmitting: false,
      isExecuting: false,
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('copies both user and assistant bubbles', async () => {
    const now = new Date();
    const todayMessageAt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 19, 27, 0, 0);
    const olderMessageAt = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 8, 5, 0, 0);
    const expectedTodayLabel = '19:27';
    const expectedOlderLabel = `${olderMessageAt.getFullYear()}/${String(olderMessageAt.getMonth() + 1).padStart(2, '0')}/${String(olderMessageAt.getDate()).padStart(2, '0')} 08:05`;

    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Need a copy.', created_at: todayMessageAt.toISOString() },
      { id: 'assistant-1', role: 'assistant', content: 'Here is the copied result.', created_at: olderMessageAt.toISOString() },
    ];

    render(<App />);

    const copyButtons = await screen.findAllByRole('button', { name: 'Copy' });
    expect(copyButtons).toHaveLength(2);
    expect(screen.getByText(expectedTodayLabel)).toBeInTheDocument();
    expect(screen.getByText(expectedOlderLabel)).toBeInTheDocument();

    fireEvent.click(copyButtons[0]);
    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenNthCalledWith(1, 'Need a copy.');
    });

    fireEvent.click(copyButtons[1]);
    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenNthCalledWith(2, 'Here is the copied result.');
    });
  });

  it('auto-scrolls when message content or tool events update', async () => {
    const baseTime = new Date().toISOString();
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Run this task.', created_at: baseTime },
      { id: 'assistant-1', role: 'assistant', content: '', created_at: baseTime, metadata: { run: { status: 'pending', scope: 'master' } } },
    ];

    const { rerender } = render(<App />);

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalled();
    });

    scrollIntoView.mockClear();
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Run this task.', created_at: baseTime },
      { id: 'assistant-1', role: 'assistant', content: 'Partial output arrived.', created_at: baseTime, metadata: { run: { status: 'pending', scope: 'master' } } },
    ];
    rerender(<App />);

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalled();
    });

    scrollIntoView.mockClear();
    mockedToolActivities = [
      {
        run_id: 'run-1',
        tool_name: 'reading_file',
        phase: 'running',
        input: { path: '/tmp/report.md' },
      },
    ];
    rerender(<App />);

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalled();
    });
  });

  it('loads older messages when the chat is scrolled near the top', async () => {
    const loadOlderMessages = vi.fn().mockResolvedValue(true);
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Earlier visible message.', created_at: new Date().toISOString() },
      { id: 'assistant-1', role: 'assistant', content: 'Latest visible message.', created_at: new Date().toISOString() },
    ];

    mockedUseSessions.mockImplementation(() => ({
      messages: mockedMessages,
      setMessages: vi.fn(),
      sessions: [
        {
          id: 'session-1',
          title: 'Session 1',
          updated_at: '2026-04-15T00:00:00Z',
          input_tokens: 0,
          output_tokens: 0,
        },
      ],
      currentSessionId: 'session-1',
      currentUsage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
      refreshSessions: vi.fn(),
      switchSession: vi.fn(),
      createNewSession: vi.fn().mockResolvedValue('session-2'),
      deleteSession: vi.fn(),
      loadOlderMessages,
      execute: vi.fn().mockResolvedValue({ status: 'started' }),
      stopActiveRun: vi.fn(),
      hasOlderMessages: true,
      isLoadingOlderMessages: false,
      isSubmitting: false,
      isExecuting: false,
    }));

    render(<App />);

    const scrollContainer = screen.getByTestId('chat-scroll-container');
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, writable: true, value: 40 });
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1200 });
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 500 });

    fireEvent.scroll(scrollContainer);

    await waitFor(() => {
      expect(loadOlderMessages).toHaveBeenCalledTimes(1);
    });
  });

  it('keeps user message content visible while the assistant is pending', async () => {
    mockedMessages = [
      {
        id: 'user-1',
        role: 'user',
        content: 'Use the seo-backlink-research skill.',
        created_at: new Date().toISOString(),
        metadata: { run: { status: 'pending', scope: 'master' } },
      },
    ];
    mockedToolActivities = [
      {
        run_id: 'run-1',
        tool_name: 'run_skill',
        phase: 'running',
        input: { skill_name: 'seo-backlink-research' },
      },
    ];

    render(<App />);

    expect(screen.getByText('Use the seo-backlink-research skill.')).toBeInTheDocument();
    expect(screen.queryByText('reading_file')).not.toBeInTheDocument();
    expect(screen.queryByText('[seo-backlink-research]')).not.toBeInTheDocument();
  });

  it('opens tool activity URLs with the system browser opener', async () => {
    const url = 'https://r.jina.ai/http://itunes.apple.com/search?term=AI%E8%AE%B0%E8%B4%A6&country=CN';
    mockedOpenUrl.mockResolvedValue(undefined);
    mockedMessages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString(),
        metadata: { run: { status: 'pending', scope: 'master' } },
      },
    ];
    mockedToolActivities = [
      {
        run_id: 'run-1',
        tool_name: 'browser_navigate',
        phase: 'complete',
        input: { url },
        duration_ms: 4402,
      },
    ];

    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: `Open ${url}` }));
    await waitFor(() => {
      expect(mockedOpenUrl).toHaveBeenCalledWith(url);
    });
  });

  it('uses the send button as stop while a run is active', async () => {
    const stopActiveRun = vi.fn();
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Run this task.', created_at: new Date().toISOString() },
      { id: 'assistant-1', role: 'assistant', content: '', created_at: new Date().toISOString(), metadata: { run: { status: 'pending', scope: 'master' } } },
    ];

    mockedUseSessions.mockImplementation(() => ({
      messages: mockedMessages,
      setMessages: vi.fn(),
      sessions: [
        {
          id: 'session-1',
          title: 'Session 1',
          updated_at: '2026-04-15T00:00:00Z',
          input_tokens: 0,
          output_tokens: 0,
        },
      ],
      currentSessionId: 'session-1',
      currentUsage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
      refreshSessions: vi.fn(),
      switchSession: vi.fn(),
      createNewSession: vi.fn().mockResolvedValue('session-2'),
      deleteSession: vi.fn(),
      loadOlderMessages: vi.fn(),
      execute: vi.fn().mockResolvedValue({ status: 'started' }),
      stopActiveRun,
      hasOlderMessages: false,
      isLoadingOlderMessages: false,
      isSubmitting: false,
      isExecuting: true,
    }));

    render(<App />);

    expect(screen.getByTestId('stop-indicator')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Stop current run' }));
    expect(stopActiveRun).toHaveBeenCalledTimes(1);
  });

  it('renders canceled state beneath the user message without an assistant bubble', async () => {
    mockedMessages = [
      {
        id: 'user-1',
        role: 'user',
        content: 'Please stop this run.',
        created_at: new Date().toISOString(),
        metadata: { run: { status: 'canceled', scope: 'master' } },
      },
    ];

    render(<App />);

    expect(screen.getByText('Please stop this run.')).toBeInTheDocument();
    expect(screen.getByText('Canceled')).toBeInTheDocument();
    expect(screen.queryByText('Run canceled.')).not.toBeInTheDocument();
    expect(screen.queryByText('reading_file')).not.toBeInTheDocument();
  });

  it('keeps the draft and shows a light notice when execute returns busy', async () => {
    const execute = vi.fn().mockResolvedValue({
      status: 'busy',
      message: 'This session is still running.',
    });

    mockedUseSessions.mockImplementation(() => ({
      messages: mockedMessages,
      setMessages: vi.fn(),
      sessions: [
        {
          id: 'session-1',
          title: 'Session 1',
          updated_at: '2026-04-15T00:00:00Z',
          input_tokens: 0,
          output_tokens: 0,
        },
      ],
      currentSessionId: 'session-1',
      currentUsage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
      refreshSessions: vi.fn(),
      switchSession: vi.fn(),
      createNewSession: vi.fn().mockResolvedValue('session-2'),
      deleteSession: vi.fn(),
      loadOlderMessages: vi.fn(),
      execute,
      stopActiveRun: vi.fn(),
      hasOlderMessages: false,
      isLoadingOlderMessages: false,
      isSubmitting: false,
      isExecuting: false,
    }));

    render(<App />);

    const textarea = screen.getByPlaceholderText('Prompt') as HTMLTextAreaElement;
    const sendButton = screen.getByRole('button', { name: 'Send with Cmd/Ctrl + Enter' });
    fireEvent.change(textarea, { target: { value: 'Keep this draft.' } });
    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(execute).toHaveBeenCalledWith('Keep this draft.');
    });

    expect(textarea.value).toBe('Keep this draft.');
    expect(screen.getByText('This session is still running.')).toBeInTheDocument();
  });
});
