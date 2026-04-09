import React, { useState, useEffect, ReactNode, useRef } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { useBackendConnection } from './hooks/useBackendConnection';
import { useSessions } from './hooks/useSessions';
import { useI18n } from './hooks/useI18n';
import { 
  Settings, 
  Send, 
  Cpu, 
  Activity,
  Terminal,
  ChevronRight,
  Save,
  Globe,
  Key,
  Plus,
  Trash2,
  RefreshCw,
  Check,
  X,
  Flame,
  Radar,
  Target,
  Link,
  PlusCircle
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { Markdown } from './components/Markdown';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const DEFAULT_FERRYMAN_WS_URL = 'ws://127.0.0.1:8000/ws';
const DEFAULT_FERRYMAN_BEARER_TOKEN = 'dev-token';

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

export default function App() {
  const [wsUrl, setWsUrl] = useState<string | null>(null);
  const connection = useBackendConnection(wsUrl);
  const { call, execute: executeInstruction, isConnected, tasks, refreshTasks, toolActivities, clearToolActivities } = connection;
  const { t, locale, changeLanguage } = useI18n();
  const {
    messages,
    execute,
    isExecuting,
    sessions,
    currentSessionId,
    currentUsage,
    refreshSessions,
    switchSession,
    createNewSession,
    deleteSession,
  } = useSessions({
    call,
    executeInstruction,
    clearToolActivities,
  });
  const [input, setInput] = useState('');
  const [currentView, setCurrentView] = useState<'chat' | 'tasks' | 'skills' | 'settings'>('chat');
  const [settingsTab, setSettingsTab] = useState<'models' | 'logs'>('models');
  const [activeModel, setActiveModel] = useState<string>('gemini:gemini-3-flash-preview');
  const [llmConfigs, setLlmConfigs] = useState<any[]>([]);
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});
  const [skills, setSkills] = useState<Array<{ name: string; description: string; version: string; author: string }>>([]);
  const [isLoadingSkills, setIsLoadingSkills] = useState(false);
  const [isRefreshingTasks, setIsRefreshingTasks] = useState(false);
  const [backendLogInfo, setBackendLogInfo] = useState<{ paths: Record<string, string>; active_log: string } | null>(null);
  const [backendLogContent, setBackendLogContent] = useState('');
  const [backendLogSource, setBackendLogSource] = useState<'app' | 'sidecar'>('app');
  const [isRefreshingLogs, setIsRefreshingLogs] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isExecuting]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [backendLogContent]);

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
      setSkills(normalizeSkillsPayload(result) as Array<{ name: string; description: string; version: string; author: string }>);
    } catch (error) {
      console.error('Failed to load skills:', error);
      setSkills([]);
    } finally {
      setIsLoadingSkills(false);
    }
  };

  // Fetch initial config
  useEffect(() => {
    if (isConnected) {
      call('get_active_model').then((res: any) => setActiveModel(res));
      call('get_llm_configs').then((res: any) => setLlmConfigs(res));
      call('get_available_models').then((res: any) => setAvailableModels(res));
      refreshSkills();
      refreshSessions();
    }
  }, [isConnected, call, refreshSessions]);

  useEffect(() => {
    if (currentView === 'skills' && isConnected) {
      refreshSkills();
    }
  }, [currentView, isConnected]);

  useEffect(() => {
    if (currentView === 'tasks' && isConnected) {
      setIsRefreshingTasks(true);
      refreshTasks()
        .catch((error) => {
          console.error('Failed to load tasks:', error);
        })
        .finally(() => {
          setIsRefreshingTasks(false);
        });
    }
  }, [currentView, isConnected, refreshTasks]);

  const handleRefreshTasks = async () => {
    if (!isConnected) return;

    setIsRefreshingTasks(true);
    try {
      await refreshTasks();
    } catch (error) {
      console.error('Failed to load tasks:', error);
    } finally {
      setIsRefreshingTasks(false);
    }
  };

  const refreshBackendLogs = async (source: 'app' | 'sidecar' = backendLogSource) => {
    if (!isConnected) return;

    setIsRefreshingLogs(true);
    try {
      const [info, logs] = await Promise.all([
        call('get_backend_log_info'),
        call('read_backend_logs', { source, lines: 160 }),
      ]);
      setBackendLogInfo(info as { paths: Record<string, string>; active_log: string });
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

  const handleSend = () => {
    if (!input.trim()) return;
    execute(input);
    setInput('');
  };

  const handleSaveConfig = async (provider: string, apiKey: string | undefined, baseUrl: string) => {
    const params: Record<string, string> = { provider, base_url: baseUrl };
    if (apiKey !== undefined) {
      params.api_key = apiKey;
    }

    await call('set_llm_config', params);
    // Refresh
    const newConfigs = await call('get_llm_configs');
    setLlmConfigs(newConfigs as any[]);
  };

  const handleSetActiveModel = async (model: string) => {
    await call('set_active_model', { model });
    setActiveModel(model);
  };

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
            onClick={() => {
              setCurrentView('tasks');
              handleRefreshTasks();
            }}
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
        <header className="h-20 border-b border-white/5 flex items-center justify-between px-10 z-10 backdrop-blur-xl bg-[#0a0a0a]/40">
          <div className="flex items-center gap-4">
            <span className="text-sm font-bold tracking-tight">
              {currentView === 'chat' ? (sessions.find(s => s.id === currentSessionId)?.title || t('chat.header_title')) : 
               currentView === 'tasks' ? t('nav.tasks') : 
               currentView === 'skills' ? t('nav.skills') :
               t('nav.settings')}
            </span>
            {currentView === 'chat' && (
              <>
                <div className="h-4 w-[1px] bg-white/10" />
                <div className="flex items-center gap-2">
                  <Cpu size={14} className="text-white/30" />
                  <select 
                    value={activeModel}
                    onChange={(e) => handleSetActiveModel(e.target.value)}
                    className="text-xs font-medium text-white/60 bg-white/5 px-2 py-1 rounded-md border border-white/10 outline-none cursor-pointer hover:bg-white/10 transition-colors appearance-none"
                  >
                    {Object.entries(availableModels).map(([provider, models]) => (
                      <optgroup key={provider} label={provider.toUpperCase()}>
                        {models.map(m => (
                          <option key={`${provider}:${m}`} value={`${provider}:${m}`} className="bg-[#0a0a0a] text-white">
                            {m}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>
              </>
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
              {/* Chat Area */}
              <div className="flex-1 overflow-y-auto p-10 space-y-8 flex flex-col scrollbar-hide">
                {messages.length === 0 ? (
                    <div className="flex-1 flex flex-col items-center justify-center pb-20 space-y-12">
                      <div className="space-y-6 flex flex-col items-center text-center">
                        <div className="w-20 h-20 rounded-[2rem] bg-white/[0.02] border border-white/5 flex items-center justify-center shadow-2xl mb-4 relative overflow-hidden group hover:border-white/20 transition-all shadow-[0_0_40px_rgba(255,255,255,0.05)]">
                           <div className="absolute inset-0 bg-gradient-to-tr from-white/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                           <Terminal className="text-white/40 group-hover:text-white/80 transition-colors" size={36} strokeWidth={1.5} />
                        </div>
                        <h2 className="text-6xl display-title text-transparent bg-clip-text bg-gradient-to-b from-white to-white/40 tracking-tight">{t('chat.welcome_title')}</h2>
                        <p className="text-white/40 max-w-lg text-lg font-medium leading-relaxed">{t('chat.welcome_subtitle')}</p>
                      </div>
                      <div className="flex flex-wrap justify-center gap-5 w-full max-w-3xl pt-8 relative">
                         <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-[1px] bg-gradient-to-r from-transparent via-white/10 to-transparent" />
                         <QuickAction 
                           icon={<Flame size={20} className="text-orange-400" />}
                           title={t('chat.quick_actions.hotspot_title')}
                           onClick={() => setInput(t('chat.quick_actions.hotspot_prompt'))}
                         />
                         <QuickAction 
                           icon={<Radar size={20} className="text-blue-400" />}
                           title={t('chat.quick_actions.scout_title')}
                           onClick={() => setInput(t('chat.quick_actions.scout_prompt'))}
                         />
                         <QuickAction 
                           icon={<Target size={20} className="text-emerald-400" />}
                           title={t('chat.quick_actions.keyword_title')}
                           onClick={() => setInput(t('chat.quick_actions.keyword_prompt'))}
                         />
                         <QuickAction 
                           icon={<Link size={20} className="text-purple-400" />}
                           title={t('chat.quick_actions.backlink_title')}
                           onClick={() => setInput(t('chat.quick_actions.backlink_prompt'))}
                         />
                         <QuickAction 
                           icon={<PlusCircle size={20} className="text-pink-400" />}
                           title={t('chat.quick_actions.creator_title')}
                           onClick={() => setInput(t('chat.quick_actions.creator_prompt'))}
                         />
                      </div>
                    </div>
                ) : (
                  messages.map((msg, i) => (
                    <motion.div
                      key={msg.id || i}
                      initial={{ opacity: 0, x: msg.role === 'user' ? 20 : -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      className={cn(
                        "max-w-[85%] rounded-[1.5rem] shadow-lg",
                        msg.role === 'user' 
                          ? "ml-auto bg-white text-[#080808] font-bold shadow-sm px-6 py-4 text-[14px]"
                          : msg.metadata?.state === 'failed'
                            ? "mr-auto bg-red-500/10 border border-red-500/30 text-red-100 backdrop-blur-md px-8 py-7 text-[15px] leading-loose markdown-container"
                            : "mr-auto bg-transparent border border-white/10 text-white/90 backdrop-blur-md px-8 py-7 text-[15px] leading-loose markdown-container"
                      )}
                    >
                      {msg.metadata?.state === 'pending' ? (
                        <div className="space-y-4">
                          <ThinkingIndicator />
                          {toolActivities.map((activity, idx) => (
                             <div key={`${activity.run_id}-${activity.tool_name}-${idx}`} className="flex items-center gap-2 text-[12px] font-mono text-white/50 bg-white/5 px-4 py-2 rounded-xl">
                                {activity.phase === 'start' || activity.phase === 'running' 
                                    ? <RefreshCw size={12} className="animate-spin text-white/40 shrink-0" />
                                    : activity.phase === 'error' 
                                        ? <X size={12} className="text-red-400 shrink-0" />
                                        : <Check size={12} className="text-green-400 shrink-0" />
                                }
                                <span className="flex-1 truncate">
                                   {
                                      // @ts-ignore
                                      (t(`tools.${activity.tool_name}`) !== `tools.${activity.tool_name}`) ? t(`tools.${activity.tool_name}`) : activity.tool_name
                                   }
                                   {activity.input && activity.input.url && <span className="ml-2 text-white/30 truncate font-normal">{activity.input.url}</span>}
                                   {activity.input && activity.input.skill_name && <span className="ml-2 text-blue-400 font-bold truncate">[{activity.input.skill_name}]</span>}
                                   {activity.input && activity.input.command && <span className="ml-2 text-orange-400 truncate font-normal">`{activity.input.command}`</span>}
                                   {activity.input && activity.input.path && <span className="ml-2 text-green-400 truncate font-normal">{activity.input.path}</span>}
                                </span>
                                {activity.duration_ms !== undefined && <span className="text-white/20 shrink-0">{activity.duration_ms}ms</span>}
                             </div>
                          ))}
                        </div>
                      ) : (
                        <Markdown content={msg.content} />
                      )}
                    </motion.div>
                  ))
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Input Area */}
              <div className="p-10 pt-0">
                <div className="relative bg-white/[0.02] backdrop-blur-xl rounded-[2rem] p-1 shadow-2xl overflow-hidden group border border-white/10 focus-within:border-white/20 transition-colors">
                  <div className="flex items-center gap-3 p-2">
                    <textarea 
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                          e.preventDefault();
                          handleSend();
                        }
                      }}
                      placeholder={t('chat.placeholder_full')} 
                      className="flex-1 bg-transparent border-none outline-none px-4 py-3 text-[15px] placeholder:text-white/20 font-medium tracking-tight text-white/90 min-h-[44px] max-h-[150px] resize-none overflow-y-auto"
                      rows={1}
                    />
                    <button 
                      onClick={handleSend}
                      disabled={isExecuting || !input.trim()}
                      className={cn(
                        "w-10 h-10 rounded-[1rem] flex flex-shrink-0 items-center justify-center transition-all active:scale-95 transform relative",
                        input.trim() 
                          ? "bg-white text-[#080808] shadow-md hover:bg-white/90 border border-white" 
                          : "bg-transparent text-white/30 border border-white/10 opacity-60 cursor-not-allowed"
                      )}
                    >
                      {isExecuting ? <ThinkingIndicator compact /> : <Send size={16} strokeWidth={input.trim() ? 2.5 : 1.5} className="relative z-10" />}
                    </button>
                  </div>
                </div>
                <div className="flex items-center justify-center gap-4 mt-6">
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
              className="flex-1 overflow-y-auto p-12"
            >
              <div className="max-w-5xl mx-auto space-y-12">
                <header className="flex items-end justify-between">
                  <div>
                    <h2 className="text-4xl font-black tracking-tight mb-2">{t('nav.tasks')}</h2>
                    <p className="text-sm text-white/30 font-medium">{t('tasks.subtitle')}</p>
                  </div>
                  <div className="flex items-center gap-3">
                     <button
                        onClick={handleRefreshTasks}
                        disabled={!isConnected || isRefreshingTasks}
                        className={cn(
                          "px-4 py-2 rounded-xl border flex items-center gap-2 shadow-sm text-[10px] font-bold uppercase tracking-widest transition-all",
                          isConnected
                            ? "bg-white/5 border-white/10 text-white hover:bg-white/10"
                            : "bg-white/[0.03] border-white/5 text-white/20 cursor-not-allowed",
                          isRefreshingTasks && "text-white/60"
                        )}
                      >
                        <RefreshCw size={14} className={cn(isRefreshingTasks && 'animate-spin')} />
                        {t('tasks.refresh')}
                      </button>
                     <div className="px-4 py-2 rounded-xl bg-white/5 border border-white/10 flex items-center gap-2 shadow-sm">
                        <div className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                        <span className="text-[10px] font-bold text-white uppercase tracking-widest">{tasks.length} {t('tasks.active_count')}</span>
                     </div>
                  </div>
                </header>

                <div className="space-y-4">
                  {tasks.length === 0 ? (
                    <div className="p-32 text-center glass rounded-[3rem] border border-white/5">
                      <Activity size={48} className="mx-auto text-white/5 mb-6" />
                      <p className="text-white/20 font-bold uppercase tracking-widest text-sm">{t('tasks.empty')}</p>
                    </div>
                  ) : (
                    tasks.map(task => (
                      <div key={task.id} className="glass rounded-[2rem] p-8 border border-white/10 flex items-center gap-8 group hover:border-white/20 transition-all relative overflow-hidden">
                        <div className="absolute inset-0 bg-gradient-to-r from-white/[0.02] to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                        <div className={cn(
                          "w-14 h-14 rounded-[1.25rem] flex items-center justify-center shrink-0 shadow-xl border border-white/5 relative z-10",
                          task.status === 'running' ? "bg-white/10 text-white" :
                          task.status === 'success' ? "bg-green-500/10 text-green-500" :
                          task.status === 'failed' ? "bg-red-500/10 text-red-500" :
                          "bg-white/5 text-white/20"
                        )}>
                          {task.status === 'running' ? <Activity size={24} className="animate-spin-slow" /> : <Terminal size={24} />}
                        </div>
                        
                        <div className="flex-1 space-y-2 relative z-10">
                          <div className="flex items-center justify-between">
                            <h4 className="text-lg font-bold tracking-tight">{task.title}</h4>
                            <span className={cn(
                              "text-[10px] px-3 py-1 rounded-full font-black uppercase tracking-widest shadow-sm",
                              task.status === 'running' ? "bg-white text-[#080808]" :
                              task.status === 'success' ? "bg-green-600/20 text-green-400 border border-green-500/20" :
                              "bg-white/10 text-white/40"
                            )}>
                              {t(`tasks.status.${task.status}`)}
                            </span>
                          </div>
                          
                          <div className="flex items-center gap-4 text-xs font-medium text-white/30 italic">
                             <span>{t('tasks.identifier')}: {task.id}</span>
                             <span>•</span>
                             <span>{task.progress || t('tasks.initializing')}</span>
                          </div>

                          {task.status === 'running' && (
                            <div className="pt-2">
                               <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                                  <motion.div 
                                    initial={{ width: 0 }}
                                    animate={{ width: '100%' }}
                                    transition={{ duration: 10, repeat: Infinity }}
                                    className="h-full bg-gradient-to-r from-white/20 via-white/80 to-white/20 bg-[length:200%_100%] animate-gradient-x"
                                  />
                               </div>
                            </div>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
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
                  <button
                    onClick={() => refreshSkills()}
                    className="px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-xs font-bold uppercase tracking-widest hover:bg-white/10 transition-colors flex items-center gap-2"
                  >
                    <RefreshCw size={14} className={cn(isLoadingSkills && 'animate-spin')} />
                    {t('skills.refresh')}
                  </button>
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
                      <div className="flex items-center gap-4">
                        <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
                          <Cpu className="text-white/60" size={20} />
                        </div>
                        <span className="text-sm font-bold tracking-tight text-white/70">{t('settings.active_model_label')}</span>
                      </div>
                      <select
                        value={activeModel}
                        onChange={(e) => handleSetActiveModel(e.target.value)}
                        className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-xs outline-none font-bold hover:bg-white/10 transition-colors cursor-pointer ring-1 ring-white/5"
                      >
                        {Object.entries(availableModels).map(([provider, models]) => (
                          <optgroup key={provider} label={provider.charAt(0).toUpperCase() + provider.slice(1)}>
                            {models.map(m => (
                              <option key={`${provider}:${m}`} value={`${provider}:${m}`}>
                                {m}
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                    </section>

                    <section className="space-y-6">
                      <header>
                        <h2 className="text-2xl font-bold tracking-tight mb-2">{t('settings.providers_title')}</h2>
                        <p className="text-sm text-white/30 font-medium">{t('settings.providers_subtitle')}</p>
                      </header>

                      <div className="grid grid-cols-1 gap-6">
                        {llmConfigs.map(config => (
                          <ProviderCard
                            key={config.provider}
                            config={config}
                            t={t}
                            onSave={(apiKey, baseUrl) => handleSaveConfig(config.provider, apiKey, baseUrl)}
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
                      <button
                        onClick={() => refreshBackendLogs(backendLogSource)}
                        className="px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-xs font-bold uppercase tracking-widest hover:bg-white/10 transition-colors flex items-center gap-2"
                      >
                        <RefreshCw size={14} className={cn(isRefreshingLogs && 'animate-spin')} />
                        {t('settings.logs_refresh')}
                      </button>
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

                      <div className="space-y-1 text-xs font-mono text-white/40">
                        <div>{t('settings.logs_app_path')}：{backendLogInfo?.paths?.app || t('settings.logs_unavailable')}</div>
                        <div>{t('settings.logs_sidecar_path')}：{backendLogInfo?.paths?.sidecar || t('settings.logs_unavailable')}</div>
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

function QuickAction({ icon, title, onClick }: { icon: ReactNode, title: string, onClick: () => void }) {
  return (
    <button 
      onClick={onClick}
      className="relative overflow-hidden p-6 rounded-[1.75rem] bg-white/[0.02] border border-white/5 hover:bg-white/[0.05] hover:border-white/20 transition-all hover:shadow-2xl hover:-translate-y-1 group w-[280px] text-left"
    >
      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.05] to-transparent -translate-x-full group-hover:animate-shimmer" />
      <div className="flex flex-col gap-5 relative z-10">
        <div className="w-12 h-12 rounded-2xl bg-white/[0.05] flex items-center justify-center border border-white/10 shadow-inner group-hover:scale-110 transition-transform">
           {icon}
        </div>
        <div>
           <h4 className="text-[14px] font-bold tracking-tight text-white/80 group-hover:text-white transition-colors">{title}</h4>
        </div>
        <ChevronRight size={18} className="absolute right-0 bottom-0 text-white/10 opacity-0 group-hover:opacity-100 group-hover:translate-x-1 group-hover:text-white/40 transition-all" />
      </div>
    </button>
  );
}

function ProviderCard({ config, onSave, t }: { config: any, onSave: (apiKey: string | undefined, baseUrl: string) => void, t: any }) {
  const [apiKey, setApiKey] = useState(config.api_key || '');
  const [baseUrl, setBaseUrl] = useState(config.base_url || config.metadata.placeholder_base_url || '');
  const [isEditing, setIsEditing] = useState(false);
  const [apiKeyDirty, setApiKeyDirty] = useState(false);

  useEffect(() => {
    setApiKey(config.api_key || '');
    setBaseUrl(config.base_url || config.metadata.placeholder_base_url || '');
    setIsEditing(false);
    setApiKeyDirty(false);
  }, [config]);

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
	                  setIsEditing(true);
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
                  setIsEditing(true);
               }}
               placeholder={config.metadata.placeholder_base_url}
               className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-white/30 transition-colors"
             />
          </div>
        </div>
      </div>

      <div className="mt-auto pt-4 relative z-10">
        <button
          onClick={() => {
            onSave(apiKeyDirty ? apiKey : undefined, baseUrl);
            setIsEditing(false);
            setApiKeyDirty(false);
          }}
          disabled={!isEditing && !apiKeyDirty && config.api_key === apiKey && config.base_url === baseUrl}
          className={cn(
            "w-full py-4 rounded-2xl text-[11px] font-bold uppercase tracking-widest shadow-lg flex items-center justify-center gap-2 group/save transition-all active:scale-[0.98]",
            isEditing || apiKeyDirty || config.api_key !== apiKey || config.base_url !== baseUrl
              ? "bg-white text-[#080808] hover:bg-white/90" 
              : "bg-white/5 text-white/20 cursor-not-allowed"
          )}
        >
          <Save size={14} className="group-hover/save:rotate-12 transition-transform" />
          {t('settings.save')}
        </button>
      </div>
    </div>
  );
}
