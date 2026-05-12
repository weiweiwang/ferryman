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
            'chat.tool_output_result': 'Execution Result',
            'chat.tool_output_error': 'Failure Reason',
            'chat.model_usage': 'Model usage',
            'chat.copy_model_usage_json': 'Copy model usage JSON',
            'chat.model_usage_requests': 'requests',
            'chat.model_usage_classifier': 'Classifier',
            'chat.unknown_model': 'Unknown model',
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
        if (method === 'get_model_routing') {
          return {
            enabled: false,
            classifier_model: 'gemini:gemini-3.1-flash-lite-preview',
            flash_model: 'gemini:gemini-3-flash-preview',
            default_model: 'system.llm.active_model',
            classifier_threshold: 80,
            classifier_timeout_seconds: 8,
          };
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
      refreshCurrentSession: vi.fn(),
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

  it('shows assistant model usage details when available', async () => {
    mockedMessages = [
      {
        id: 'assistant-usage-1',
        role: 'assistant',
        content: 'Done.',
        created_at: new Date().toISOString(),
        metadata: {
          model_usage: {
            version: 1,
            request: {
              total: { input_tokens: 1200, output_tokens: 300, total_tokens: 1500 },
              by_model: {
                'gemini:gemini-3-flash-preview': {
                  input_tokens: 800,
                  output_tokens: 180,
                  total_tokens: 980,
                  request_count: 2,
                },
                'deepseek:deepseek-v4-pro': {
                  input_tokens: 400,
                  output_tokens: 120,
                  total_tokens: 520,
                  request_count: 1,
                },
              },
            },
            classifier: {
              model: 'gemini:gemini-3.1-flash-lite-preview',
              input_tokens: 300,
              output_tokens: 20,
              total_tokens: 320,
              request_count: 3,
            },
          },
        },
      },
    ];

    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Model usage' }));

    expect(screen.getByText('1,500 Tokens')).toBeInTheDocument();
    expect(screen.getByText('gemini:gemini-3-flash-preview')).toBeInTheDocument();
    expect(screen.getByText('deepseek:deepseek-v4-pro')).toBeInTheDocument();
    expect(screen.getByText('Classifier')).toBeInTheDocument();
    expect(screen.getByText('gemini:gemini-3.1-flash-lite-preview')).toBeInTheDocument();
  });

  it('updates the active model select immediately after choosing a model', async () => {
    let activeModel = 'qwen:qwen3.6-plus';
    const call = vi.fn(async (method: string, params?: Record<string, string>) => {
      if (method === 'get_active_model') {
        return activeModel;
      }
      if (method === 'get_model_readiness') {
        return { ready: true, active_model: activeModel, issue: null };
      }
      if (method === 'get_llm_configs') {
        return [
          { provider: 'qwen', api_key: '', base_url: '', model: '', metadata: { label: 'Qwen' } },
          { provider: 'deepseek', api_key: '', base_url: '', model: '', metadata: { label: 'DeepSeek' } },
        ];
      }
      if (method === 'get_available_models') {
        return {
          qwen: ['qwen3.6-plus'],
          deepseek: ['deepseek-v4-pro'],
        };
      }
      if (method === 'get_model_routing') {
        return {
          enabled: false,
          classifier_model: 'gemini:gemini-3.1-flash-lite-preview',
          flash_model: 'gemini:gemini-3-flash-preview',
          default_model: 'system.llm.active_model',
          classifier_threshold: 80,
          classifier_timeout_seconds: 8,
        };
      }
      if (method === 'set_active_model') {
        activeModel = params?.model || activeModel;
        return { status: 'success' };
      }
      if (method === 'list_skills') {
        return [];
      }
      if (method === 'read_backend_logs') {
        return { content: '' };
      }
      return {};
    });

    mockedUseBackendConnection.mockImplementation(() => ({
      call,
      execute: vi.fn(),
      cancelRun: vi.fn(),
      isConnected: true,
      tasks: [],
      toolActivities: mockedToolActivities,
      lastEvent: null,
      refreshTasks: vi.fn(),
      clearToolActivities: vi.fn(),
    }));

    render(<App />);

    const select = await screen.findByDisplayValue('qwen3.6-plus') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'deepseek:deepseek-v4-pro' } });

    await waitFor(() => {
      expect(select.value).toBe('deepseek:deepseek-v4-pro');
    });
    expect(call).toHaveBeenCalledWith('set_active_model', { model: 'deepseek:deepseek-v4-pro' });
  });

  it('auto-scrolls when message content or tool events update', async () => {
    const baseTime = new Date().toISOString();
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Run this task.', created_at: baseTime },
      { id: 'assistant-1', role: 'assistant', content: '', created_at: baseTime, metadata: { run: { id: 'run-1', status: 'pending' } } },
    ];

    const { rerender } = render(<App />);

    await waitFor(() => {
      expect(scrollIntoView).toHaveBeenCalled();
    });

    scrollIntoView.mockClear();
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Run this task.', created_at: baseTime },
      { id: 'assistant-1', role: 'assistant', content: 'Partial output arrived.', created_at: baseTime, metadata: { run: { id: 'run-1', status: 'pending' } } },
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
      refreshCurrentSession: vi.fn(),
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
        metadata: { run: { id: 'run-1', status: 'pending' } },
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
        metadata: { run: { id: 'run-1', status: 'pending' } },
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

  it('only shows tool activities for the pending assistant run', async () => {
    mockedMessages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString(),
        metadata: { run: { id: 'run-visible', status: 'pending' } },
      },
    ];
    mockedToolActivities = [
      {
        session_id: 'XcJ2uTt8Qiw7v2viJJwHDf',
        run_id: 'run-visible',
        tool_name: 'list_files',
        phase: 'complete',
        input: { path: '/Users/wangweiwei/.ferryman/workspaces/XcJ2uTt8Qiw7v2viJJwHDf/reports' },
      },
      {
        session_id: 'kwhjvdjQWKjCaZdoQqZF8x',
        run_id: 'run-other',
        tool_name: 'write_file',
        phase: 'complete',
        input: { path: '/Users/wangweiwei/.ferryman/workspaces/kwhjvdjQWKjCaZdoQqZF8x/reports/resize.html' },
      },
    ];

    render(<App />);

    expect(screen.getByText('/Users/wangweiwei/.ferryman/workspaces/XcJ2uTt8Qiw7v2viJJwHDf/reports')).toBeInTheDocument();
    expect(screen.queryByText('/Users/wangweiwei/.ferryman/workspaces/kwhjvdjQWKjCaZdoQqZF8x/reports/resize.html')).not.toBeInTheDocument();
  });

  it('expands tool activity output inline for complete and failed tools', async () => {
    mockedMessages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString(),
        metadata: { run: { id: 'run-1', status: 'pending' } },
      },
    ];
    mockedToolActivities = [
      {
        run_id: 'run-1',
        event_id: 'event-complete',
        tool_name: 'run_skill_script',
        phase: 'complete',
        duration_ms: 25,
        output: 'stdout: generated report.csv',
      },
      {
        run_id: 'run-1',
        event_id: 'event-error',
        tool_name: 'write_file',
        phase: 'error',
        duration_ms: 8,
        output: 'Permission denied: report.csv',
      },
    ];

    render(<App />);

    expect(screen.queryByText('Execution Result')).not.toBeInTheDocument();
    expect(screen.queryByText('Failure Reason')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('run_skill_script'));
    expect(screen.getByText('Execution Result')).toBeInTheDocument();
    expect(screen.getByText('stdout: generated report.csv')).toBeInTheDocument();

    fireEvent.click(screen.getByText('write_file'));
    expect(screen.getByText('Failure Reason')).toBeInTheDocument();
    expect(screen.getByText('Permission denied: report.csv')).toBeInTheDocument();
  });

  it('uses the send button as stop while a run is active', async () => {
    const stopActiveRun = vi.fn();
    mockedMessages = [
      { id: 'user-1', role: 'user', content: 'Run this task.', created_at: new Date().toISOString() },
      { id: 'assistant-1', role: 'assistant', content: '', created_at: new Date().toISOString(), metadata: { run: { status: 'pending' } } },
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
      refreshCurrentSession: vi.fn(),
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
        metadata: { run: { status: 'canceled' } },
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
      refreshCurrentSession: vi.fn(),
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
