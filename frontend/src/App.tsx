import React, { useState, useEffect, useLayoutEffect, ReactNode, useRef, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { openUrl } from '@tauri-apps/plugin-opener';
import { useBackendConnection, type ToolActivityPayload } from './hooks/useBackendConnection';
import { useSessions, type Message, type MessageRunStatus } from './hooks/useSessions';
import { useI18n } from './hooks/useI18n';
import { 
  Settings, 
  Send, 
  Cpu, 
  Activity,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  Save,
  Globe,
  Key,
  Plus,
  Trash2,
  RefreshCw,
  Check,
  Copy,
  X,
  Flame,
  Radar,
  Target,
  Link,
  TrendingUp,
  Gauge,
  ExternalLink
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { Markdown } from './components/Markdown';
import { RefreshIconButton } from './components/RefreshIconButton';
import { ScheduleManager } from './components/ScheduleManager';
import { TaskManager } from './components/TaskManager';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const DEFAULT_FERRYMAN_WS_URL = 'ws://127.0.0.1:8000/ws';
const DEFAULT_FERRYMAN_BEARER_TOKEN = 'dev-token';
const CHAT_RAIL_CLASS = 'mx-auto w-full max-w-[72rem]';

function buildWebSocketUrl(baseUrl: string, token?: string) {
  if (!token) {
    return baseUrl;
  }

  const url = new URL(baseUrl);
  url.searchParams.set('access_token', token);
  return url.toString();
}

function getDefaultWebSocketUrl() {
  const baseUrl = import.meta.env.VITE_FERRYMAN_WS_URL || DEFAULT_FERRYMAN_WS_URL;
  const token = import.meta.env.VITE_FERRYMAN_BEARER_TOKEN || DEFAULT_FERRYMAN_BEARER_TOKEN;
  return buildWebSocketUrl(baseUrl, token);
}

function isTauriRuntime() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

const CHROME_DOWNLOAD_URL = 'https://www.google.com/chrome/';

type ProviderMetadata = {
  label: string;
  placeholder_base_url?: string;
  placeholder_model?: string;
  supports_model?: boolean;
};

type LlmProviderConfig = {
  provider: string;
  api_key: string;
  base_url: string;
  model?: string;
  metadata: ProviderMetadata;
};

type BrowserRuntimeStatus = {
  available: boolean;
  path?: string | null;
  required?: boolean;
  download_url?: string;
};

type ModelReadinessIssueCode =
  | 'no_runnable_model'
  | 'missing_api_key'
  | 'missing_base_url'
  | 'active_model_invalid';

type ModelReadinessIssue = {
  code: ModelReadinessIssueCode;
  provider?: string;
  missing?: string[];
};

type ModelReadiness = {
  ready: boolean;
  active_model: string | null;
  issue: ModelReadinessIssue | null;
};

type SendMode = 'mod_enter' | 'enter';

type SkillSummary = {
  name: string;
  description: string;
  version: string;
  author: string;
  created?: string | null;
  updated?: string | null;
};

function buildModelOptionValue(provider: string, model: string) {
  return `${provider}:${model}`;
}

function getToolActivityDisplayName(toolName: string, t: (key: string) => string) {
  const translated = t(`tools.${toolName}`);
  return translated !== `tools.${toolName}` ? translated : toolName;
}

function getHttpUrl(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }

  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? value : null;
  } catch {
    return null;
  }
}

function buildToolActivityCopyLine(activity: ToolActivityPayload, t: (key: string) => string) {
  const segments = [getToolActivityDisplayName(activity.tool_name, t)];

  if (activity.input?.url) {
    segments.push(String(activity.input.url));
  }
  if (activity.input?.skill_name) {
    segments.push(`[${String(activity.input.skill_name)}]`);
  }
  if (activity.input?.command) {
    segments.push(String(activity.input.command));
  }
  if (activity.input?.path) {
    segments.push(String(activity.input.path));
  }
  if (activity.input?.title) {
    segments.push(`"${String(activity.input.title)}"`);
  }
  if (activity.duration_ms !== undefined) {
    segments.push(`${activity.duration_ms}ms`);
  }

  return segments.join(' ');
}

function getMessageCopyText(
  message: Message,
  toolActivities: ToolActivityPayload[],
  t: (key: string) => string,
) {
  if (!isAssistantPendingMessage(message)) {
    return message.content.trim();
  }

  const activityLines = toolActivities.map((activity) => buildToolActivityCopyLine(activity, t));
  return [message.content.trim(), ...activityLines].filter(Boolean).join('\n').trim();
}

function getMessageRunStatus(message: Message): MessageRunStatus | undefined {
  return message.metadata?.run?.status;
}

function isAssistantPendingMessage(message: Message): boolean {
  return message.role === 'assistant' && getMessageRunStatus(message) === 'pending';
}

function getUserRunStatusLabel(message: Message, t: (key: string) => string): string | null {
  if (message.role !== 'user') {
    return null;
  }

  if (getMessageRunStatus(message) === 'canceled') {
    return t('chat.status_canceled');
  }

  return null;
}

function pad2(value: number) {
  return String(value).padStart(2, '0');
}

function formatMessageTimestamp(createdAt?: string) {
  if (!createdAt) {
    return '';
  }

  const messageDate = new Date(createdAt);
  if (Number.isNaN(messageDate.getTime())) {
    return '';
  }

  const now = new Date();
  const isToday =
    messageDate.getFullYear() === now.getFullYear() &&
    messageDate.getMonth() === now.getMonth() &&
    messageDate.getDate() === now.getDate();
  const timePart = `${pad2(messageDate.getHours())}:${pad2(messageDate.getMinutes())}`;

  if (isToday) {
    return timePart;
  }

  return `${messageDate.getFullYear()}/${pad2(messageDate.getMonth() + 1)}/${pad2(messageDate.getDate())} ${timePart}`;
}

export default function App() {
  const [wsUrl, setWsUrl] = useState<string | null>(null);
  const connection = useBackendConnection(wsUrl);
  const { call, execute: executeInstruction, cancelRun, isConnected, toolActivities, clearToolActivities, lastEvent } = connection;
  const { t, locale, changeLanguage } = useI18n();
  const {
    messages,
    execute,
    stopActiveRun,
    isSubmitting,
    isExecuting,
    sessions,
    currentSessionId,
    currentUsage,
    refreshSessions,
    switchSession,
    createNewSession,
    deleteSession,
    loadOlderMessages,
    hasOlderMessages,
    isLoadingOlderMessages,
  } = useSessions({
    call,
    executeInstruction,
    cancelRun,
    clearToolActivities,
    lastEvent,
    isConnected,
  });
  const [input, setInput] = useState('');
  const [sendMode, setSendMode] = useState<SendMode>(() => (
    localStorage.getItem('ferryman_send_mode') === 'enter' ? 'enter' : 'mod_enter'
  ));
  const [isSendMenuOpen, setIsSendMenuOpen] = useState(false);
  const [currentView, setCurrentView] = useState<'chat' | 'tasks' | 'schedules' | 'skills' | 'settings'>('chat');
  const [settingsTab, setSettingsTab] = useState<'models' | 'logs'>('models');
  const [activeModel, setActiveModel] = useState<string | null>(null);
  const [modelReadiness, setModelReadiness] = useState<ModelReadiness | null>(null);
  const [llmConfigs, setLlmConfigs] = useState<LlmProviderConfig[]>([]);
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [isLoadingSkills, setIsLoadingSkills] = useState(false);
  const [isRefreshingModels, setIsRefreshingModels] = useState(false);
  const [backendLogContent, setBackendLogContent] = useState('');
  const [backendLogSource, setBackendLogSource] = useState<'app' | 'sidecar'>('app');
  const [isRefreshingLogs, setIsRefreshingLogs] = useState(false);
  const [browserRuntimeStatus, setBrowserRuntimeStatus] = useState<BrowserRuntimeStatus | null>(null);
  const [copiedMessageKey, setCopiedMessageKey] = useState<string | null>(null);
  const [composerNotice, setComposerNotice] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const chatContentRef = useRef<HTMLDivElement>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const didApplyInitialModelRouteRef = useRef(false);
  const copyResetTimerRef = useRef<number | null>(null);
  const pendingHistoryScrollOffsetRef = useRef<number | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const autoScrollSessionRef = useRef(currentSessionId);
  const sendShortcutHint = sendMode === 'enter' ? t('chat.send_shortcut_enter_hint') : t('chat.send_shortcut_mod_enter_hint');

  const scrollChatToBottom = useCallback(() => {
    const scrollContainer = chatScrollRef.current;
    if (!scrollContainer) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' });
      return;
    }

    scrollContainer.scrollTop = scrollContainer.scrollHeight;
    messagesEndRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' });
    shouldStickToBottomRef.current = true;
  }, []);

  useEffect(() => {
    localStorage.setItem('ferryman_send_mode', sendMode);
  }, [sendMode]);

  useEffect(() => {
    if (!composerNotice) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setComposerNotice((current) => (current === composerNotice ? null : current));
    }, 3200);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [composerNotice]);
  useLayoutEffect(() => {
    if (currentView !== 'chat') {
      return;
    }

    const scrollContainer = chatScrollRef.current;
    const pendingHistoryScrollOffset = pendingHistoryScrollOffsetRef.current;
    if (scrollContainer && pendingHistoryScrollOffset !== null) {
      scrollContainer.scrollTop = scrollContainer.scrollHeight - pendingHistoryScrollOffset;
      pendingHistoryScrollOffsetRef.current = null;
      return;
    }

    const sessionChanged = autoScrollSessionRef.current !== currentSessionId;
    if (sessionChanged) {
      autoScrollSessionRef.current = currentSessionId;
      shouldStickToBottomRef.current = true;
    }

    if (!sessionChanged && !shouldStickToBottomRef.current) {
      return;
    }

    scrollChatToBottom();
    const frameId = window.requestAnimationFrame(() => {
      scrollChatToBottom();
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [currentSessionId, currentView, messages, scrollChatToBottom, toolActivities]);

  useEffect(() => {
    if (currentView !== 'chat') {
      return;
    }

    const resizeTarget = chatContentRef.current || chatScrollRef.current;
    if (!resizeTarget || typeof ResizeObserver === 'undefined') {
      return;
    }

    const observer = new ResizeObserver(() => {
      if (pendingHistoryScrollOffsetRef.current === null && shouldStickToBottomRef.current) {
        scrollChatToBottom();
      }
    });

    observer.observe(resizeTarget);
    return () => {
      observer.disconnect();
    };
  }, [currentView, scrollChatToBottom]);

  const handleChatScroll = useCallback((event: React.UIEvent<HTMLDivElement>) => {
    const scrollContainer = event.currentTarget;
    const distanceToBottom = scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight;
    shouldStickToBottomRef.current = distanceToBottom < 120;

    if (
      scrollContainer.scrollTop > 80 ||
      !hasOlderMessages ||
      isLoadingOlderMessages ||
      !loadOlderMessages
    ) {
      return;
    }

    pendingHistoryScrollOffsetRef.current = scrollContainer.scrollHeight - scrollContainer.scrollTop;
    loadOlderMessages().then((loaded) => {
      if (!loaded) {
        pendingHistoryScrollOffsetRef.current = null;
      }
    });
  }, [hasOlderMessages, isLoadingOlderMessages, loadOlderMessages]);

  useEffect(() => () => {
    if (copyResetTimerRef.current !== null) {
      window.clearTimeout(copyResetTimerRef.current);
    }
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [backendLogContent]);

  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) {
      return;
    }

    textarea.style.height = '0px';
    textarea.style.height = `${Math.min(Math.max(textarea.scrollHeight, 72), 220)}px`;
  }, [input]);

  useEffect(() => {
    let cancelled = false;

    const resolveConnection = async () => {
      if (!isTauriRuntime() || import.meta.env.DEV) {
        setWsUrl(getDefaultWebSocketUrl());
        return;
      }

      try {
        const connection = await invoke<{ wsUrl: string; accessToken: string }>('get_backend_connection');
        if (!cancelled) {
          setWsUrl(buildWebSocketUrl(connection.wsUrl, connection.accessToken));
        }
      } catch (error) {
        console.error('Failed to initialize Ferryman backend connection:', error);
        if (!cancelled) {
          setWsUrl(getDefaultWebSocketUrl());
        }
      }
    };

    resolveConnection();

    return () => {
      cancelled = true;
    };
  }, []);

  const normalizeSkillsPayload = (payload: any) => {
    if (Array.isArray(payload)) {
      return payload;
    }
    if (Array.isArray(payload?.skills)) {
      return payload.skills;
    }
    return [];
  };

  const refreshSkills = async () => {
    if (!isConnected) return;

    setIsLoadingSkills(true);
    try {
      const result = await call('list_skills');
      setSkills(normalizeSkillsPayload(result) as SkillSummary[]);
    } catch (error) {
      console.error('Failed to load skills:', error);
      setSkills([]);
    } finally {
      setIsLoadingSkills(false);
    }
  };

  const refreshModelSettings = async () => {
    if (!isConnected) return;

    setIsRefreshingModels(true);
    try {
      const [model, readiness, configs, models] = await Promise.all([
        call('get_active_model'),
        call('get_model_readiness'),
        call('get_llm_configs'),
        call('get_available_models'),
      ]);
      const nextReadiness = readiness as ModelReadiness;
      setActiveModel((model as string | null) ?? null);
      setModelReadiness(nextReadiness);
      setLlmConfigs(configs as LlmProviderConfig[]);
      setAvailableModels(models as Record<string, string[]>);

      if (!didApplyInitialModelRouteRef.current) {
        didApplyInitialModelRouteRef.current = true;
        if (!nextReadiness.ready) {
          setSettingsTab('models');
          setCurrentView('settings');
        }
      }
    } catch (error) {
      console.error('Failed to refresh model settings:', error);
    } finally {
      setIsRefreshingModels(false);
    }
  };

  // Fetch initial config
  useEffect(() => {
    if (isConnected) {
      if (isTauriRuntime()) {
        invoke('report_frontend_smoke_status', { status: 'backend_connected' }).catch((error) => {
          console.error('Failed to report frontend smoke status:', error);
        });
      }
      refreshModelSettings();
      refreshSkills();
      refreshSessions();
      call('get_browser_runtime_status')
        .then((status) => setBrowserRuntimeStatus(status as BrowserRuntimeStatus))
        .catch((error) => {
          console.error('Failed to check browser runtime:', error);
          setBrowserRuntimeStatus(null);
        });
    }
  }, [isConnected, call, refreshSessions]);

  useEffect(() => {
    if (currentView === 'skills' && isConnected) {
      refreshSkills();
    }
  }, [currentView, isConnected]);

  const refreshBackendLogs = async (source: 'app' | 'sidecar' = backendLogSource) => {
    if (!isConnected) return;

    setIsRefreshingLogs(true);
    try {
      const logs = await call('read_backend_logs', { source, lines: 160 });
      setBackendLogContent((logs as { content: string }).content || '');
      setBackendLogSource(source);
    } catch (error) {
      console.error('Failed to load backend logs:', error);
      setBackendLogContent(t('settings.logs_load_failed'));
    } finally {
      setIsRefreshingLogs(false);
    }
  };

  useEffect(() => {
    if (isConnected) {
      refreshBackendLogs('app');
    }
  }, [isConnected]);

  const handleSend = async () => {
    if (isExecuting) {
      stopActiveRun();
      return;
    }
    if (!modelReadiness?.ready || !input.trim()) return;
    const submittedInstruction = input;
    const result = await execute(submittedInstruction);
    if (result.status === 'started') {
      setComposerNotice(null);
      setInput((current) => (current === submittedInstruction ? '' : current));
      return;
    }

    if (result.message) {
      setComposerNotice(result.message);
    }
  };

  const handleCopyMessage = useCallback(async (messageKey: string, text: string) => {
    if (!text.trim()) {
      return;
    }

    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageKey(messageKey);

      if (copyResetTimerRef.current !== null) {
        window.clearTimeout(copyResetTimerRef.current);
      }

      copyResetTimerRef.current = window.setTimeout(() => {
        setCopiedMessageKey((current) => (current === messageKey ? null : current));
      }, 1600);
    } catch (error) {
      console.error('Failed to copy message:', error);
    }
  }, []);

  const handleOpenChromeDownload = async () => {
    try {
      await openUrl(CHROME_DOWNLOAD_URL);
    } catch (error) {
      console.error('Failed to open Chrome download URL:', error);
      window.open(CHROME_DOWNLOAD_URL, '_blank', 'noopener,noreferrer');
    }
  };

  const handleOpenExternalUrl = useCallback(async (url: string) => {
    try {
      await openUrl(url);
    } catch (error) {
      console.error('Failed to open external URL:', error);
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }, []);

  const handleSaveConfig = async (
    provider: string,
    apiKey: string | undefined,
    baseUrl: string,
    model?: string
  ) => {
    const params: Record<string, string> = { provider, base_url: baseUrl };
    if (apiKey !== undefined) {
      params.api_key = apiKey;
    }
    if (model !== undefined) {
      params.model = model;
    }

    const result = await call('set_llm_config', params) as { status?: string; message?: string };
    if (result?.status === 'error') {
      throw new Error(result.message || 'Failed to validate provider configuration.');
    }
    await refreshModelSettings();
  };

  const handleSetActiveModel = async (model: string) => {
    await call('set_active_model', { model });
    await refreshModelSettings();
  };

  const providerLabels = Object.fromEntries(
    llmConfigs.map((config) => [config.provider, config.metadata?.label || config.provider])
  );
  const availableModelValues = Object.entries(availableModels).flatMap(([provider, models]) =>
    models.map((model) => buildModelOptionValue(provider, model))
  );
  const selectedModelValue = activeModel && availableModelValues.includes(activeModel) ? activeModel : '';
  const isModelReady = modelReadiness?.ready ?? true;
  const shouldWarnModelSelector = modelReadiness?.issue?.code === 'no_runnable_model';
  const shouldHighlightModelSelector = availableModelValues.length > 0 && !selectedModelValue;
  const modelSelectorPlaceholder = getModelSelectorPlaceholder(t, modelReadiness?.issue, availableModelValues.length);
  const inlineModelHint = getInlineModelHint(t, modelReadiness?.issue, availableModelValues.length);

  return (
    <div className="flex w-full h-full bg-transparent text-white selection:bg-white/20 selection:text-white font-sans">
      {/* Sidebar */}
      <aside className="w-72 border-r border-white/5 flex flex-col glass z-10 transition-all duration-300">
        <div className="p-6 pb-4">
          <div className="flex items-center gap-3">
            <img src="/favicon.png" alt="Ferryman Logo" className="w-10 h-10 rounded-xl shadow-xl ring-1 ring-white/10 object-cover" />
            <div>
              <h1 className="font-bold text-lg leading-tight tracking-tight">{t('app.title')}</h1>
              <p className="text-[10px] text-white/40 uppercase tracking-[0.2em] font-bold">{t('app.subtitle')}</p>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 space-y-1 custom-scrollbar">
          <div className="px-2 mb-4 mt-2 flex items-center justify-between group/header">
            <h3 className="text-[11px] font-black text-white/50 uppercase tracking-[0.2em]">{t('nav.recent_sessions')}</h3>
            <button 
              onClick={() => {
                createNewSession().then(() => setCurrentView('chat'));
              }}
              className="w-6 h-6 rounded-md flex items-center justify-center text-white/60 bg-white/5 border border-white/10 hover:bg-white/15 hover:text-white transition-all shadow-sm shrink-0"
              title={t('nav.new_chat')}
            >
              <Plus size={14} strokeWidth={2} />
            </button>
          </div>
          
          {sessions.map(s => (
            <div 
              key={s.id}
              onClick={() => {
                switchSession(s.id);
                setCurrentView('chat');
              }}
              className={cn(
                "group relative p-3.5 rounded-2xl transition-all cursor-pointer flex flex-col gap-1.5 border border-transparent",
                currentSessionId === s.id ? "bg-white/5 border-white/10 shadow-xl" : "hover:bg-white/[0.04]"
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cn(
                  "text-sm font-bold truncate flex-1 tracking-tight",
                  currentSessionId === s.id ? "text-white" : "text-white/50 group-hover:text-white/80"
                )}>
                  {s.title || t('chat.untitled')}
                </span>
                <button 
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteSession(s.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-red-500/20 hover:text-red-400 rounded-lg transition-all"
                >
                  <Trash2 size={13} />
                </button>
              </div>
              <div className="flex items-center gap-2">
                 <div className="text-[9px] font-black text-white/40 px-2 py-0.5 rounded-md bg-white/5 border border-white/5 group-hover:text-white/60 group-hover:border-white/10 transition-all uppercase tracking-wider">
                    {(s.input_tokens + s.output_tokens).toLocaleString()} {t('tasks.tokens_unit')}
                 </div>
              </div>
            </div>
          ))}
        </div>

        <nav className="p-4 space-y-1 border-t border-white/5 mt-auto">
          <NavItem 
            icon={<Activity size={18}/>} 
            label={t('nav.tasks')} 
            active={currentView === 'tasks'}
            onClick={() => setCurrentView('tasks')}
          />
          <NavItem
            icon={<CalendarClock size={18}/>}
            label={t('nav.schedules')}
            active={currentView === 'schedules'}
            onClick={() => setCurrentView('schedules')}
          />
          <NavItem
            icon={<Cpu size={18}/>}
            label={t('nav.skills')}
            active={currentView === 'skills'}
            onClick={() => setCurrentView('skills')}
          />
          <NavItem 
            icon={<Settings size={18}/>} 
            label={t('nav.settings')} 
            active={currentView === 'settings'}
            onClick={() => {
              setSettingsTab('models');
              setCurrentView('settings');
            }}
          />
          
          <div className="flex items-center gap-2 pt-4 px-2">
            <button 
              onClick={() => changeLanguage('zh')}
              className={cn("text-[9px] font-bold px-2 py-1 rounded transition-colors", locale === 'zh' ? "bg-white text-[#080808]" : "bg-white/5 text-white/40 hover:bg-white/10")}
            >ZH</button>
            <button 
              onClick={() => changeLanguage('en')}
              className={cn("text-[9px] font-bold px-2 py-1 rounded transition-colors", locale === 'en' ? "bg-white text-[#080808]" : "bg-white/5 text-white/40 hover:bg-white/10")}
            >EN</button>
            <div className="ml-auto flex items-center gap-2">
              <div className={cn(
                "w-1.5 h-1.5 rounded-full",
                isConnected ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]" : "bg-red-500 animate-pulse"
              )} />
            </div>
          </div>
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col relative overflow-hidden">
        {/* Animated Background Overlay */}
        <div className="absolute inset-0 bg-gradient-to-b from-white/[0.02] via-transparent to-transparent pointer-events-none" />
        
        {/* Header */}
        <header className="h-16 border-b border-white/5 flex items-center justify-between px-8 z-10 backdrop-blur-xl bg-[#0a0a0a]/55">
          <div className="flex items-center gap-4">
            {currentView === 'chat' && (
              <div className="flex items-center gap-2">
                <Cpu size={14} className="text-white/30" />
                <select 
                  value={selectedModelValue}
                  onChange={(e) => handleSetActiveModel(e.target.value)}
                  className="text-xs font-medium text-white/60 bg-white/5 px-2 py-1 rounded-md border border-white/10 outline-none cursor-pointer hover:bg-white/10 transition-colors appearance-none"
                >
                  <option value="" disabled>
                    {t('settings.no_models')}
                  </option>
                  {Object.entries(availableModels).map(([provider, models]) => (
                    <optgroup key={provider} label={providerLabels[provider] || provider.toUpperCase()}>
                      {models.map(m => (
                        <option key={buildModelOptionValue(provider, m)} value={buildModelOptionValue(provider, m)} className="bg-[#0a0a0a] text-white">
                          {m}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="flex items-center">
            {currentView === 'chat' && (
               <div className="flex items-center gap-4 bg-white/[0.04] border border-white/10 rounded-full px-5 py-2 backdrop-blur-md shadow-sm">
                   <div className="flex items-center gap-2">
                     <span className="text-[9px] font-black text-white/40 uppercase tracking-widest leading-none">{t('tasks.token_in')}</span>
                     <span className="text-white/80 font-mono text-[11px] font-medium leading-none">{currentUsage.input_tokens.toLocaleString()}</span>
                   </div>
                   <div className="w-[1px] h-3 bg-white/10" />
                   <div className="flex items-center gap-2">
                     <span className="text-[9px] font-black text-white/40 uppercase tracking-widest leading-none">{t('tasks.token_out')}</span>
                     <span className="text-white/80 font-mono text-[11px] font-medium leading-none">{currentUsage.output_tokens.toLocaleString()}</span>
                   </div>
                   <div className="w-[1px] h-3 bg-white/20" />
                   <div className="flex items-center gap-2">
                     <span className="text-[9px] font-black text-white/70 uppercase tracking-widest leading-none">{t('tasks.token_total')}</span>
                     <span className="text-white font-mono text-[11px] font-bold leading-none">{currentUsage.total_tokens.toLocaleString()}</span>
                   </div>
                </div>
            )}
          </div>
        </header>

        <AnimatePresence mode="wait">
          {currentView === 'chat' ? (
            <motion.div 
              key="chat"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="flex-1 flex flex-col overflow-hidden"
            >
              {browserRuntimeStatus && !browserRuntimeStatus.available && (
                <BrowserRuntimeBanner t={t} onOpenChromeDownload={handleOpenChromeDownload} />
              )}
              {/* Chat Area */}
              <div
                ref={chatScrollRef}
                onScroll={handleChatScroll}
                data-testid="chat-scroll-container"
                className="flex-1 overflow-y-auto p-8 space-y-8 flex flex-col scrollbar-hide"
              >
                {messages.length === 0 ? (
                    <div className="flex-1 flex items-center justify-center pb-10">
                      <div className={CHAT_RAIL_CLASS}>
                        {isModelReady ? (
                          <>
                            <div className="mb-8 flex items-end justify-between gap-8">
                              <div className="space-y-3">
                                <h2 className="display-title text-5xl leading-none text-white/90">{t('chat.welcome_title')}</h2>
                              </div>
                              <p className="hidden max-w-xs text-right text-sm font-medium leading-6 text-white/38 md:block">{t('chat.welcome_subtitle')}</p>
                            </div>

                            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-6">
                             <QuickAction
                               index="01"
                               icon={<Flame size={16} className="text-orange-300" />}
                               title={t('chat.quick_actions.hotspot_title')}
                               onClick={() => setInput(t('chat.quick_actions.hotspot_prompt'))}
                             />
                             <QuickAction
                               index="02"
                               icon={<Radar size={16} className="text-sky-300" />}
                               title={t('chat.quick_actions.scout_title')}
                               onClick={() => setInput(t('chat.quick_actions.scout_prompt'))}
                             />
                             <QuickAction
                               index="03"
                               icon={<Target size={16} className="text-emerald-300" />}
                               title={t('chat.quick_actions.keyword_title')}
                               onClick={() => setInput(t('chat.quick_actions.keyword_prompt'))}
                             />
                             <QuickAction
                               index="04"
                               icon={<Link size={16} className="text-violet-300" />}
                               title={t('chat.quick_actions.backlink_title')}
                               onClick={() => setInput(t('chat.quick_actions.backlink_prompt'))}
                             />
                             <QuickAction
                               index="05"
                               icon={<TrendingUp size={16} className="text-rose-300" />}
                               title={t('chat.quick_actions.stock_title')}
                               onClick={() => setInput(t('chat.quick_actions.stock_prompt'))}
                             />
                             <QuickAction
                               index="06"
                               icon={<Gauge size={16} className="text-cyan-300" />}
                               title={t('chat.quick_actions.daily_dashboard_title')}
                               onClick={() => setInput(t('chat.quick_actions.daily_dashboard_prompt'))}
                             />
                            </div>
                          </>
                        ) : (
                          <ModelSetupGuide
                            t={t}
                            issue={modelReadiness?.issue}
                            onOpenSettings={() => {
                              setSettingsTab('models');
                              setCurrentView('settings');
                            }}
                          />
                        )}
                      </div>
                    </div>
                ) : (
                  <div ref={chatContentRef} className={cn(CHAT_RAIL_CLASS, "flex flex-col gap-8")}>
                    {messages.map((msg, i) => {
                      const messageKey = msg.id || `${msg.role}-${i}`;
                      const copyText = getMessageCopyText(msg, toolActivities, t);
                      const isCopied = copiedMessageKey === messageKey;
                      const timestampLabel = formatMessageTimestamp(msg.created_at);
                      const userRunStatusLabel = getUserRunStatusLabel(msg, t);
                      const bubbleShellClass = cn(
                        "relative rounded-[1.5rem] shadow-lg",
                        msg.role === 'user'
                          ? "bg-white text-[#080808] font-bold shadow-sm px-6 py-4 text-[14px]"
                          : getMessageRunStatus(msg) === 'failed'
                            ? "bg-red-500/10 border border-red-500/30 text-red-100 backdrop-blur-md px-8 py-7 text-[15px] leading-loose markdown-container"
                            : "bg-transparent border border-white/10 text-white/90 backdrop-blur-md px-8 py-7 text-[15px] leading-loose markdown-container"
                      );
                      const metaBarClass = cn(
                        "absolute bottom-0 flex items-center gap-2 px-1 py-1 text-[12px] font-medium opacity-0 translate-y-1 transition-all duration-200 group-hover/message:translate-y-0 group-hover/message:opacity-100 group-focus-within/message:translate-y-0 group-focus-within/message:opacity-100",
                        msg.role === 'user'
                          ? "right-1 text-white/65"
                          : "left-1 text-white/55"
                      );

                      return (
                      <motion.div
                        key={messageKey}
                        initial={{ opacity: 0, x: msg.role === 'user' ? 20 : -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        className={cn(
                          "group/message relative max-w-[85%] pb-11",
                          msg.role === 'user'
                            ? "ml-auto"
                            : "mr-auto"
                        )}
                      >
                        <div className={bubbleShellClass}>
                          {isAssistantPendingMessage(msg) ? (
                            <div className="space-y-4">
                              <ThinkingIndicator />
                              {toolActivities.map((activity, idx) => (
                                <div key={`${activity.run_id}-${activity.tool_name}-${idx}`} className="flex items-center gap-2 text-[12px] font-mono text-white/50 bg-white/5 px-4 py-2 rounded-xl">
                                  {(() => {
                                    const activityUrl = getHttpUrl(activity.input?.url);

                                    return (
                                      <>
                                        {activity.phase === 'start' || activity.phase === 'running'
                                        ? <RefreshCw size={12} className="animate-spin text-white/40 shrink-0" />
                                        : activity.phase === 'error'
                                            ? <X size={12} className="text-red-400 shrink-0" />
                                            : <Check size={12} className="text-green-400 shrink-0" />
                                        }
                                        <span className="flex min-w-0 flex-1 items-center gap-2 truncate">
                                          <span className="shrink-0">{getToolActivityDisplayName(activity.tool_name, t)}</span>
                                          {activityUrl && (
                                            <button
                                              type="button"
                                              onClick={() => handleOpenExternalUrl(activityUrl)}
                                              className="inline-flex min-w-0 items-center gap-1 truncate text-left font-normal text-sky-300/75 transition-colors hover:text-sky-200"
                                              title={activityUrl}
                                              aria-label={`Open ${activityUrl}`}
                                            >
                                              <span className="truncate">{activityUrl}</span>
                                              <ExternalLink size={11} className="shrink-0" />
                                            </button>
                                          )}
                                          {activity.input && activity.input.url && !activityUrl && <span className="truncate font-normal text-white/30">{activity.input.url}</span>}
                                          {activity.input && activity.input.skill_name && <span className="truncate font-bold text-blue-400">[{activity.input.skill_name}]</span>}
                                          {activity.input && activity.input.command && <span className="truncate font-normal text-orange-400">`{activity.input.command}`</span>}
                                          {activity.input && activity.input.path && (
                                            <span
                                              className="truncate font-normal text-green-400"
                                              title={String(activity.input.path)}
                                            >
                                              {String(activity.input.path)}
                                            </span>
                                          )}
                                          {activity.input && activity.input.title && <span className="truncate text-white/40 italic">"{activity.input.title}"</span>}
                                        </span>
                                        {activity.duration_ms !== undefined && <span className="text-white/20 shrink-0">{activity.duration_ms}ms</span>}
                                      </>
                                    );
                                  })()}
                                </div>
                              ))}
                            </div>
                          ) : (
                            <Markdown content={msg.content} />
                          )}
                        </div>
                        {userRunStatusLabel ? (
                          <div className="mt-2 flex justify-end px-1">
                            <span className="inline-flex items-center rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] font-medium text-white/60">
                              {userRunStatusLabel}
                            </span>
                          </div>
                        ) : null}
                        {(copyText || timestampLabel) ? (
                          <div className={metaBarClass}>
                            {copyText ? (
                              <button
                                type="button"
                                onClick={() => handleCopyMessage(messageKey, copyText)}
                                aria-label={isCopied ? t('common.copied') : t('common.copy')}
                                title={isCopied ? t('common.copied') : t('common.copy')}
                                className={cn(
                                  "flex h-5 w-5 items-center justify-center transition-colors",
                                  msg.role === 'user'
                                    ? "text-white/58 hover:text-white/82"
                                    : "text-white/48 hover:text-white"
                                )}
                              >
                                {isCopied ? <Check size={14} strokeWidth={2.4} /> : <Copy size={14} strokeWidth={2.2} />}
                              </button>
                            ) : null}
                            {timestampLabel ? (
                              <span className="tabular-nums tracking-[0.01em]">{timestampLabel}</span>
                            ) : null}
                          </div>
                        ) : null}
                      </motion.div>
                    )})}
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Input Area */}
              <div className="px-8 pb-8 pt-0">
                {isModelReady ? (
                  <div className={cn(CHAT_RAIL_CLASS, "relative z-20 bg-white/[0.025] backdrop-blur-xl rounded-xl p-1 shadow-2xl group border border-white/10 focus-within:border-white/25 transition-colors")}>
                    <div className="flex items-center gap-3 p-2">
                      <textarea
                        ref={inputRef}
                        value={input}
                        onChange={(e) => {
                          setInput(e.target.value);
                          if (composerNotice) {
                            setComposerNotice(null);
                          }
                        }}
                        onKeyDown={(e) => {
                          if (e.key !== 'Enter' || e.nativeEvent.isComposing) {
                            return;
                          }
                          if (sendMode === 'enter' && !e.shiftKey) {
                            e.preventDefault();
                            handleSend();
                            return;
                          }
                          if (sendMode === 'mod_enter' && (e.metaKey || e.ctrlKey)) {
                            e.preventDefault();
                            handleSend();
                          }
                        }}
                        placeholder={t('chat.placeholder')}
                        className="flex-1 bg-transparent border-none outline-none px-4 py-4 text-[15px] placeholder:text-white/20 font-medium tracking-tight text-white/90 min-h-[72px] max-h-[220px] resize-none overflow-y-auto"
                        rows={1}
                      />
                      <div className="relative flex flex-shrink-0 items-center pr-1">
                        <div
                          className={cn(
                            "flex rounded-lg border transition-all",
                            isExecuting
                              ? "border-white/18 bg-white/[0.08] text-white shadow-[0_14px_34px_rgba(255,255,255,0.08)]"
                              : input.trim()
                                ? "border-white bg-white text-[#080808] shadow-md"
                                : "border-white/10 bg-white/[0.03] text-white/35"
                          )}
                        >
                          <button
                            onClick={handleSend}
                            disabled={isSubmitting || (!isExecuting && !input.trim())}
                            aria-label={isExecuting ? t('chat.stop') : sendShortcutHint}
                            className={cn(
                              "group relative h-10 w-10 flex items-center justify-center rounded-l-lg transition-colors active:scale-95 disabled:cursor-not-allowed",
                              isExecuting
                                ? "hover:bg-white/[0.08]"
                                : input.trim()
                                  ? "hover:bg-black/[0.04]"
                                  : "opacity-55"
                            )}
                          >
                            <span className="pointer-events-none absolute bottom-full left-1/2 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-[#111] px-2 py-1 font-mono text-[10px] font-bold tracking-[0.04em] text-white/60 opacity-0 shadow-xl transition-opacity group-hover:opacity-100">
                              {isExecuting ? t('chat.stop') : sendShortcutHint}
                            </span>
                            {isExecuting ? (
                              <StopIndicator />
                            ) : isSubmitting ? (
                              <RefreshCw size={16} strokeWidth={2.4} className="relative z-10 animate-spin" data-testid="send-submitting-indicator" />
                            ) : (
                              <Send size={17} strokeWidth={input.trim() ? 2.5 : 1.5} className="relative z-10" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => setIsSendMenuOpen((open) => !open)}
                            className={cn(
                              "flex h-10 w-7 items-center justify-center rounded-r-lg border-l transition-colors",
                              input.trim()
                                ? "border-black/10 hover:bg-black/[0.05]"
                                : "border-white/10 hover:bg-white/[0.06]"
                            )}
                            title={t('chat.send_mode')}
                          >
                            <ChevronDown size={13} strokeWidth={2.4} />
                          </button>
                        </div>
                        {isSendMenuOpen && (
                          <div className="absolute bottom-full right-0 z-50 mb-2 w-48 overflow-hidden rounded-xl border border-white/10 bg-[#101010] p-1 shadow-2xl">
                            {(['mod_enter', 'enter'] as SendMode[]).map((mode) => (
                              <button
                                key={mode}
                                type="button"
                                onClick={() => {
                                  setSendMode(mode);
                                  setIsSendMenuOpen(false);
                                }}
                                className={cn(
                                  "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs font-bold transition-colors",
                                  sendMode === mode ? "bg-white text-[#080808]" : "text-white/60 hover:bg-white/[0.06] hover:text-white"
                                )}
                              >
                                <span>{mode === 'enter' ? t('chat.send_mode_enter') : t('chat.send_mode_mod_enter')}</span>
                                <span className="font-mono text-[10px] opacity-60">{mode === 'enter' ? '↵' : '⌘↵'}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                    {composerNotice ? (
                      <div className="px-4 pb-3 text-xs font-medium text-white/58">
                        {composerNotice}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className="flex items-center justify-center gap-4 mt-4">
                  <p className="text-[10px] text-white/10 font-bold uppercase tracking-[0.1em]">{t('app.byok_enabled')}</p>
                  <div className="h-1 w-1 rounded-full bg-white/10" />
                  <p className="text-[10px] text-white/10 font-bold uppercase tracking-[0.1em]">{t('app.deterministic_kernel')}</p>
                </div>
              </div>
            </motion.div>
          ) : currentView === 'tasks' ? (
            <motion.div
              key="tasks"
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98 }}
              className="flex-1 overflow-hidden"
            >
              <TaskManager call={call} isConnected={isConnected} t={t} />
            </motion.div>
          ) : currentView === 'schedules' ? (
            <motion.div
              key="schedules"
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98 }}
              className="flex-1 overflow-hidden"
            >
              <ScheduleManager call={call} isConnected={isConnected} t={t} />
            </motion.div>
          ) : currentView === 'skills' ? (
            <motion.div
              key="skills"
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98 }}
              className="flex-1 overflow-y-auto p-12 custom-scrollbar"
            >
              <div className="max-w-5xl mx-auto space-y-12 pb-20">
                <header className="flex items-end justify-between gap-4">
                  <div>
                    <h2 className="text-4xl font-black tracking-tight mb-2">{t('skills.title')}</h2>
                    <p className="text-sm text-white/30 font-medium">{t('skills.subtitle')}</p>
                  </div>
                  <RefreshIconButton
                    onClick={() => refreshSkills()}
                    isLoading={isLoadingSkills}
                    label={t('skills.refresh')}
                  />
                </header>

                <div className="space-y-4">
                  {isLoadingSkills && skills.length === 0 ? (
                    <div className="p-20 text-center glass rounded-[3rem] border border-white/5">
                      <RefreshCw size={48} className="mx-auto text-white/10 mb-6 animate-spin" />
                      <p className="text-white/30 font-bold uppercase tracking-widest text-sm">{t('skills.loading')}</p>
                    </div>
                  ) : skills.length === 0 ? (
                    <div className="p-20 text-center glass rounded-[3rem] border border-white/5">
                      <Cpu size={48} className="mx-auto text-white/5 mb-6" />
                      <p className="text-white/20 font-bold uppercase tracking-widest text-sm">{t('skills.empty')}</p>
                    </div>
                  ) : (
                    skills.map((skill) => (
                      <div key={skill.name} className="glass rounded-[2rem] p-8 border border-white/10 space-y-4">
                        <div className="flex items-start justify-between gap-6">
                          <div className="space-y-2">
                            <h3 className="text-xl font-bold tracking-tight">{skill.name}</h3>
                            <p className="text-sm text-white/60 leading-relaxed">{skill.description}</p>
                          </div>
                          <div className="shrink-0 text-right text-xs text-white/35 space-y-1 font-medium">
                            <div>{t('skills.version')}: {skill.version || '0.1.0'}</div>
                            <div>{t('skills.author')}: {skill.author || t('skills.unknown_author')}</div>
                            <div>{t('skills.created')}: {skill.created || t('skills.unknown_date')}</div>
                            <div>{t('skills.updated')}: {skill.updated || t('skills.unknown_date')}</div>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div 
              key="settings"
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98 }}
              className="flex-1 overflow-y-auto p-12 custom-scrollbar"
            >
              <div className="max-w-5xl mx-auto space-y-12 pb-20">
                <header className="flex items-end justify-between gap-4">
                  <div>
                    <h2 className="text-4xl font-black tracking-tight mb-2">{t('nav.settings')}</h2>
                    <p className="text-sm text-white/30 font-medium">{t('settings.subtitle')}</p>
                  </div>
                  <div className="flex items-center gap-3 rounded-2xl bg-white/5 border border-white/10 p-1">
                    <button
                      onClick={() => setSettingsTab('models')}
                      className={cn(
                        'px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-colors',
                        settingsTab === 'models' ? 'bg-white text-[#080808]' : 'text-white/50 hover:bg-white/10'
                      )}
                    >
                      {t('settings.tabs.models')}
                    </button>
                    <button
                      onClick={() => {
                        setSettingsTab('logs');
                        refreshBackendLogs(backendLogSource);
                      }}
                      className={cn(
                        'px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-colors',
                        settingsTab === 'logs' ? 'bg-white text-[#080808]' : 'text-white/50 hover:bg-white/10'
                      )}
                    >
                      {t('settings.tabs.logs')}
                    </button>
                  </div>
                </header>

                {settingsTab === 'models' ? (
                  <div className="space-y-12">
                    <section className="flex items-center justify-between glass rounded-3xl p-6 border border-white/10 shadow-xl">
                      <div className="flex items-start gap-4">
                        <div className="w-10 h-10 rounded-xl border border-white/10 bg-white/5 flex items-center justify-center shrink-0">
                          <Cpu className="text-white/60" size={20} />
                        </div>
                        <div className="space-y-1.5">
                          <span className="text-sm font-bold tracking-tight text-white/70">{t('settings.active_model_label')}</span>
                          {!isModelReady && (
                            <p className="max-w-2xl text-xs font-medium leading-5 text-white/48">{inlineModelHint}</p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="relative">
                          {(shouldWarnModelSelector || shouldHighlightModelSelector) && (
                            <span
                              className={cn(
                                "pointer-events-none absolute left-3.5 top-1/2 h-2 w-2 -translate-y-1/2 rounded-full",
                                shouldWarnModelSelector
                                  ? "bg-amber-300 shadow-[0_0_0_4px_rgba(252,211,77,0.08)]"
                                  : "bg-sky-300 shadow-[0_0_0_4px_rgba(125,211,252,0.08)]"
                              )}
                            />
                          )}
                          <select
                            value={selectedModelValue}
                            onChange={(e) => handleSetActiveModel(e.target.value)}
                            className={cn(
                              "min-w-[18rem] rounded-xl py-2.5 pr-4 text-xs font-bold outline-none transition-all cursor-pointer ring-1 appearance-none",
                              shouldWarnModelSelector
                                ? "pl-8 border border-amber-300/55 bg-black/40 text-amber-50 ring-amber-300/20 shadow-[0_0_0_1px_rgba(252,211,77,0.12),0_10px_30px_rgba(245,158,11,0.08)] hover:border-amber-200/70 hover:text-white"
                                : shouldHighlightModelSelector
                                  ? "pl-8 border border-sky-200/35 bg-sky-300/[0.08] text-white ring-sky-300/15 shadow-[0_0_0_1px_rgba(125,211,252,0.12),0_10px_30px_rgba(56,189,248,0.08)] hover:border-sky-100/45 hover:bg-sky-300/[0.12]"
                                  : "pl-4 border border-white/10 bg-white/5 ring-white/5 hover:bg-white/10"
                            )}
                          >
                            <option value="" disabled>
                              {modelSelectorPlaceholder}
                            </option>
                            {Object.entries(availableModels).map(([provider, models]) => (
                              <optgroup key={provider} label={providerLabels[provider] || provider.charAt(0).toUpperCase() + provider.slice(1)}>
                                {models.map(m => (
                                  <option key={buildModelOptionValue(provider, m)} value={buildModelOptionValue(provider, m)}>
                                    {m}
                                  </option>
                                ))}
                              </optgroup>
                            ))}
                          </select>
                        </div>
                      </div>
                    </section>

                    <section className="space-y-6">
                      <header className="flex items-center justify-between gap-4">
                        <div>
                          <h2 className="text-2xl font-bold tracking-tight mb-2">{t('settings.providers_title')}</h2>
                          <p className="text-sm text-white/30 font-medium">{t('settings.providers_subtitle')}</p>
                        </div>
                        <RefreshIconButton
                          onClick={() => refreshModelSettings()}
                          disabled={!isConnected || isRefreshingModels}
                          isLoading={isRefreshingModels}
                          label={t('settings.models_refresh')}
                        />
                      </header>

                      <div className="grid grid-cols-1 gap-6">
                        {llmConfigs.map(config => (
                          <ProviderCard
                            key={config.provider}
                            config={config}
                            t={t}
                            onSave={(apiKey, baseUrl, model) => handleSaveConfig(config.provider, apiKey, baseUrl, model)}
                          />
                        ))}
                      </div>
                    </section>
                  </div>
                ) : (
                  <section className="space-y-6">
                    <header className="flex items-center justify-between gap-4">
                      <div>
                        <h2 className="text-2xl font-bold tracking-tight mb-2">{t('settings.logs_title')}</h2>
                        <p className="text-sm text-white/30 font-medium">{t('settings.logs_subtitle')}</p>
                      </div>
                      <RefreshIconButton
                        onClick={() => refreshBackendLogs(backendLogSource)}
                        isLoading={isRefreshingLogs}
                        label={t('settings.logs_refresh')}
                      />
                    </header>

                    <div className="glass rounded-3xl p-6 border border-white/10 shadow-xl space-y-4">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => refreshBackendLogs('app')}
                          className={cn(
                            'px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-colors',
                            backendLogSource === 'app' ? 'bg-white text-[#080808]' : 'bg-white/5 text-white/50 hover:bg-white/10'
                          )}
                        >
                          {t('settings.logs_app_tab')}
                        </button>
                        <button
                          onClick={() => refreshBackendLogs('sidecar')}
                          className={cn(
                            'px-3 py-2 rounded-xl text-xs font-bold uppercase tracking-widest transition-colors',
                            backendLogSource === 'sidecar' ? 'bg-white text-[#080808]' : 'bg-white/5 text-white/50 hover:bg-white/10'
                          )}
                        >
                          {t('settings.logs_sidecar_tab')}
                        </button>
                      </div>

                      <pre className="min-h-[280px] max-h-[420px] overflow-auto rounded-2xl bg-black/30 border border-white/5 p-4 text-xs leading-6 text-white/75 whitespace-pre-wrap break-words">
                        {backendLogContent || t('settings.logs_empty')}
                        <div ref={logsEndRef} />
                      </pre>
                    </div>
                  </section>
                )}

	              </div>
	            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

function ThinkingIndicator({ compact = false }: { compact?: boolean }) {
  const size = compact ? 'w-2.5 h-2.5' : 'w-3 h-3';
  return (
    <div className={cn('flex items-center py-1', compact ? 'justify-center' : 'justify-start')}>
      <motion.div
        animate={{ scale: [0.9, 1.25, 0.9], opacity: [0.45, 1, 0.45] }}
        transition={{ duration: 1.1, repeat: Infinity, ease: 'easeInOut' }}
        className={cn(size, 'rounded-full bg-white/85')}
      />
    </div>
  );
}

function StopIndicator() {
  return (
    <div className="relative flex h-4 w-4 items-center justify-center" data-testid="stop-indicator">
      <motion.span
        aria-hidden="true"
        className="absolute inset-[-4px] rounded-[8px] bg-current/18 blur-[6px]"
        animate={{ scale: [0.82, 1.22, 0.82], opacity: [0.16, 0.52, 0.16] }}
        transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.span
        aria-hidden="true"
        className="absolute inset-[-1px] rounded-[5px] border border-current/30"
        animate={{ scale: [0.88, 1.16, 0.88], opacity: [0.28, 0.82, 0.28] }}
        transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.span
        className="relative z-10 block h-[10px] w-[10px] rounded-[3px] bg-current"
        animate={{ scale: [0.86, 1.1, 0.86], opacity: [0.7, 1, 0.7] }}
        transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
      />
    </div>
  );
}

function NavItem({ icon, label, active = false, onClick }: { icon: React.ReactNode, label: string, active?: boolean, onClick?: () => void }) {
  return (
    <div 
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 px-4 py-3 rounded-2xl transition-all duration-200 cursor-pointer group",
        active ? "bg-white/[0.04] text-white ring-1 ring-white/10" : "text-white/40 hover:text-white hover:bg-white/5"
      )}
    >
      <div className={cn(
        "transition-transform duration-300 group-hover:scale-110",
        active ? "text-white" : "text-white/40 group-hover:text-white"
      )}>
        {icon}
      </div>
      <span className="text-sm font-semibold flex-1">{label}</span>
      {active && <ChevronRight size={14} className="opacity-50" />}
    </div>
  );
}

function QuickAction({
  icon,
  index,
  title,
  onClick,
}: {
  icon: ReactNode;
  index: string;
  title: string;
  onClick: () => void;
}) {
  return (
    <button 
      onClick={onClick}
      className="group relative min-h-[92px] overflow-hidden rounded-lg border border-white/8 bg-white/[0.025] p-3.5 text-left transition-all hover:-translate-y-0.5 hover:border-white/22 hover:bg-white/[0.06] hover:shadow-[0_18px_45px_rgba(0,0,0,0.25)]"
    >
      <div className="absolute inset-x-3 top-0 h-px bg-gradient-to-r from-transparent via-white/18 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="relative z-10 flex h-full flex-col justify-between gap-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md border border-white/10 bg-black/20 shadow-inner transition-transform group-hover:scale-105">
             {icon}
          </div>
          <span className="font-mono text-[10px] font-bold tabular-nums text-white/18 transition-colors group-hover:text-white/35">{index}</span>
        </div>
        <div className="flex items-end justify-between gap-2">
           <h4 className="text-[13px] font-bold leading-5 tracking-tight text-white/72 transition-colors group-hover:text-white">{title}</h4>
           <ChevronRight size={14} className="shrink-0 translate-x-0 text-white/12 transition-all group-hover:translate-x-0.5 group-hover:text-white/45" />
        </div>
      </div>
    </button>
  );
}

function getModelReadinessDescription(t: (key: string) => string, issue?: ModelReadinessIssue | null) {
  switch (issue?.code) {
    case 'missing_api_key':
      return t('settings.setup_missing_api_key');
    case 'missing_base_url':
      return t('settings.setup_missing_base_url');
    case 'active_model_invalid':
      return t('settings.setup_active_model_invalid');
    case 'no_runnable_model':
    default:
      return t('settings.setup_no_runnable_model');
  }
}

function getInlineModelHint(
  t: (key: string) => string,
  issue: ModelReadinessIssue | null | undefined,
  availableModelCount: number
) {
  if (availableModelCount > 0) {
    return t('settings.inline_select_model_hint');
  }

  switch (issue?.code) {
    case 'missing_base_url':
      return t('settings.inline_missing_base_url_hint');
    case 'missing_api_key':
    case 'no_runnable_model':
    case 'active_model_invalid':
    default:
      return t('settings.inline_model_hint');
  }
}

function getModelSelectorPlaceholder(
  t: (key: string) => string,
  issue: ModelReadinessIssue | null | undefined,
  availableModelCount: number
) {
  if (availableModelCount > 0) {
    return t('settings.select_model_placeholder');
  }

  switch (issue?.code) {
    case 'missing_base_url':
      return t('settings.missing_base_url_placeholder');
    case 'missing_api_key':
    case 'no_runnable_model':
    case 'active_model_invalid':
    default:
      return t('settings.no_models');
  }
}

function ModelSetupGuide({
  t,
  issue,
  onOpenSettings,
}: {
  t: (key: string) => string;
  issue?: ModelReadinessIssue | null;
  onOpenSettings: () => void;
}) {
  return (
    <section className="relative overflow-hidden rounded-[2rem] border border-amber-200/12 bg-[linear-gradient(135deg,rgba(255,243,211,0.11),rgba(255,255,255,0.02))] px-8 py-9 shadow-[0_28px_90px_rgba(0,0,0,0.26)] backdrop-blur-xl">
      <div className="absolute inset-y-0 left-0 w-px bg-gradient-to-b from-transparent via-amber-100/35 to-transparent" />
      <div className="absolute inset-x-10 top-0 h-px bg-gradient-to-r from-transparent via-amber-100/24 to-transparent" />
      <div className="relative z-10 flex flex-col gap-6">
        <div className="space-y-2">
          <h3 className="text-4xl font-black tracking-tight text-amber-50">{t('settings.setup_welcome_title')}</h3>
          <p className="max-w-3xl text-base font-medium leading-7 text-white/76">
            {getModelReadinessDescription(t, issue)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onOpenSettings}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-white px-4 py-3 text-[11px] font-black uppercase tracking-[0.16em] text-[#080808] transition-colors hover:bg-white/92"
          >
            {t('settings.open_model_settings')}
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}

function BrowserRuntimeBanner({
  t,
  onOpenChromeDownload,
}: {
  t: (key: string) => string;
  onOpenChromeDownload: () => void;
}) {
  return (
    <div className="mx-10 mt-6 rounded-[1.5rem] border border-amber-300/20 bg-amber-400/[0.08] p-4 shadow-[0_20px_60px_rgba(0,0,0,0.18)] backdrop-blur-xl">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-amber-300/20 bg-amber-300/10 text-amber-100">
            <Globe size={18} />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-black tracking-tight text-amber-50">{t('browser.chrome_required.title')}</p>
            <p className="max-w-3xl text-xs font-medium leading-5 text-white/65">{t('browser.chrome_required.description')}</p>
          </div>
        </div>
        <button
          onClick={onOpenChromeDownload}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-2xl bg-white px-4 py-2.5 text-[10px] font-black uppercase tracking-[0.18em] text-[#080808] transition-all hover:bg-white/90 active:scale-[0.98]"
        >
          {t('browser.chrome_required.download')}
          <ExternalLink size={13} />
        </button>
      </div>
    </div>
  );
}

function ProviderCard({
  config,
  onSave,
  t,
}: {
  config: LlmProviderConfig;
  onSave: (apiKey: string | undefined, baseUrl: string, model?: string) => Promise<void>;
  t: any;
}) {
  const [apiKey, setApiKey] = useState(config.api_key || '');
  const [baseUrl, setBaseUrl] = useState(config.base_url || '');
  const [model, setModel] = useState(config.model || '');
  const [apiKeyDirty, setApiKeyDirty] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setApiKey(config.api_key || '');
    setBaseUrl(config.base_url || '');
    setModel(config.model || '');
    setApiKeyDirty(false);
    setSaveError(null);
  }, [config]);

  const supportsModel = Boolean(config.metadata.supports_model);
  const apiKeyChanged = apiKeyDirty && apiKey !== (config.api_key || '');
  const baseUrlChanged = baseUrl !== (config.base_url || '');
  const modelChanged = supportsModel && model !== (config.model || '');
  const hasChanges = apiKeyChanged || baseUrlChanged || modelChanged;

  return (
    <div className="glass rounded-[2.5rem] p-6 border border-white/5 space-y-6 relative overflow-hidden group min-h-[280px] flex flex-col">
      <div className="absolute inset-0 bg-gradient-to-br from-white/[0.03] to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
      
      <div className="flex items-center justify-between relative z-10">
        <h3 className="text-lg font-bold tracking-tight">{config.metadata.label}</h3>
        <div className={cn(
          "px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border",
          config.api_key ? "bg-green-500/10 text-green-400 border-green-500/20" : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
        )}>
          {config.api_key ? t('settings.linked') : t('settings.missing')}
        </div>
      </div>

      <div className="space-y-4 relative z-10">
        {saveError && (
          <div className="rounded-lg border border-red-400/20 bg-red-500/10 px-3 py-2 text-xs leading-5 text-red-100">
            {saveError}
          </div>
        )}
        <div className="space-y-2">
          <label className="text-[10px] font-bold text-white/20 uppercase tracking-widest ml-1">{t('settings.api_key')}</label>
          <div className="relative">
             <Key size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20" />
             <input 
               type="password" 
               value={apiKey}
	               onChange={(e) => {
	                  setApiKey(e.target.value);
	                  setApiKeyDirty(true);
	               }}
	               placeholder={t('settings.api_key_placeholder')}
	               className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-white/30 transition-colors"
	             />
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-[10px] font-bold text-white/20 uppercase tracking-widest ml-1">{t('settings.base_url')}</label>
          <div className="relative">
             <Globe size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20" />
             <input 
               type="text" 
               value={baseUrl}
               onChange={(e) => {
                  setBaseUrl(e.target.value);
               }}
               placeholder={config.metadata.placeholder_base_url}
               className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-white/30 transition-colors"
             />
          </div>
        </div>

        {supportsModel && (
          <div className="space-y-2">
            <label className="text-[10px] font-bold text-white/20 uppercase tracking-widest ml-1">{t('settings.model')}</label>
            <div className="relative">
              <Cpu size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-white/20" />
              <input
                type="text"
                value={model}
                onChange={(e) => {
                  setModel(e.target.value);
                }}
                placeholder={config.metadata.placeholder_model || t('settings.model_placeholder')}
                className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-white/30 transition-colors"
              />
            </div>
          </div>
        )}
      </div>

      <div className="mt-auto pt-4 relative z-10">
        <button
          onClick={async () => {
            setSaveError(null);
            setIsSaving(true);
            try {
              await onSave(apiKeyDirty ? apiKey : undefined, baseUrl, modelChanged ? model : undefined);
              setApiKeyDirty(false);
            } catch (error) {
              const message = error instanceof Error ? error.message : String(error);
              setSaveError(message);
            } finally {
              setIsSaving(false);
            }
          }}
          disabled={!hasChanges || isSaving}
          className={cn(
            "w-full py-4 rounded-2xl text-[11px] font-bold uppercase tracking-widest shadow-lg flex items-center justify-center gap-2 group/save transition-all active:scale-[0.98]",
            hasChanges && !isSaving
              ? "bg-white text-[#080808] hover:bg-white/90" 
              : "bg-white/5 text-white/20 cursor-not-allowed"
          )}
        >
          <Save size={14} className="group-hover/save:rotate-12 transition-transform" />
          {isSaving ? t('settings.validating') : t('settings.save')}
        </button>
      </div>
    </div>
  );
}
