import React, { useState, useEffect, ReactNode } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
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
  Trash2
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { Markdown } from './components/Markdown';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export default function App() {
  const { 
    messages, isConnected, execute, call, tasks,
    sessions, currentSessionId, currentUsage,
    refreshSessions, switchSession, createNewSession, deleteSession 
  } = useWebSocket('ws://localhost:8000/ws');
  const { t, locale, changeLanguage } = useI18n();
  const [input, setInput] = useState('');
  const [currentView, setCurrentView] = useState<'chat' | 'tasks' | 'settings'>('chat');
  const [activeModel, setActiveModel] = useState<string>('gemini:gemini-3-flash-preview');
  const [llmConfigs, setLlmConfigs] = useState<any[]>([]);
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});

  // Fetch initial config
  useEffect(() => {
    if (isConnected) {
      call('get_active_model').then((res: any) => setActiveModel(res));
      call('get_llm_configs').then((res: any) => setLlmConfigs(res));
      call('get_available_models').then((res: any) => setAvailableModels(res));
      refreshSessions();
    }
  }, [isConnected, call, refreshSessions]);

  const handleSend = () => {
    if (!input.trim()) return;
    execute(input);
    setInput('');
  };

  const handleSaveConfig = async (provider: string, apiKey: string, baseUrl: string) => {
    await call('set_llm_config', { provider, api_key: apiKey, base_url: baseUrl });
    // Refresh
    const newConfigs = await call('get_llm_configs');
    setLlmConfigs(newConfigs as any[]);
  };

  const handleSetActiveModel = async (model: string) => {
    await call('set_active_model', { model });
    setActiveModel(model);
  };

  return (
    <div className="flex w-full h-full bg-[#0a0a0a] text-white selection:bg-blue-500/30 font-sans">
      {/* Sidebar */}
      <aside className="w-72 border-r border-white/5 flex flex-col glass z-10 transition-all duration-300">
        <div className="p-6">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 via-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20 ring-1 ring-white/10">
              <Cpu size={22} className="text-white drop-shadow-md" />
            </div>
            <div>
              <h1 className="font-bold text-lg leading-tight tracking-tight">{t('app.title')}</h1>
              <p className="text-[10px] text-white/40 uppercase tracking-[0.2em] font-bold">{t('app.subtitle')}</p>
            </div>
          </div>

          <button 
            onClick={() => {
              createNewSession().then(() => setCurrentView('chat'));
            }}
            className="w-full py-3 px-4 rounded-xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.08] hover:border-white/10 transition-all flex items-center gap-3 group mb-6"
          >
            <div className="w-8 h-8 rounded-lg bg-blue-600/10 flex items-center justify-center text-blue-500 group-hover:bg-blue-600 group-hover:text-white transition-all">
              <Plus size={18} />
            </div>
            <span className="text-sm font-bold text-white/60 group-hover:text-white transition-colors">开启新对话</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 space-y-1 custom-scrollbar">
          <div className="px-2 mb-4 flex items-center justify-between">
            <h3 className="text-[11px] font-black text-white/50 uppercase tracking-[0.2em]">最近对话</h3>
            <div className="h-[1px] flex-1 ml-4 bg-white/5" />
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
                  {s.title || '新对话'}
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
                    {(s.input_tokens + s.output_tokens).toLocaleString()} Tokens
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
            icon={<Settings size={18}/>} 
            label={t('nav.settings')} 
            active={currentView === 'settings'}
            onClick={() => setCurrentView('settings')}
          />
          
          <div className="flex items-center gap-2 pt-4 px-2">
            <button 
              onClick={() => changeLanguage('zh')}
              className={cn("text-[9px] font-bold px-2 py-1 rounded transition-colors", locale === 'zh' ? "bg-blue-600 text-white" : "bg-white/5 text-white/40 hover:bg-white/10")}
            >ZH</button>
            <button 
              onClick={() => changeLanguage('en')}
              className={cn("text-[9px] font-bold px-2 py-1 rounded transition-colors", locale === 'en' ? "bg-blue-600 text-white" : "bg-white/5 text-white/40 hover:bg-white/10")}
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
        <div className="absolute inset-0 bg-gradient-to-b from-blue-500/[0.02] via-transparent to-transparent pointer-events-none" />
        
        {/* Header */}
        <header className="h-20 border-b border-white/5 flex items-center justify-between px-10 z-10 backdrop-blur-xl bg-[#0a0a0a]/40">
          <div className="flex items-center gap-4">
            <span className="text-sm font-bold tracking-tight">
              {currentView === 'chat' ? (sessions.find(s => s.id === currentSessionId)?.title || '对话') : 
               currentView === 'tasks' ? t('nav.tasks') : 
               t('nav.settings')}
            </span>
            <div className="h-4 w-[1px] bg-white/10" />
            <div className="flex items-center gap-2">
              <Cpu size={14} className="text-blue-500/50" />
              <select 
                value={activeModel}
                onChange={(e) => handleSetActiveModel(e.target.value)}
                className="text-xs font-medium text-blue-400/80 bg-blue-400/10 px-2 py-1 rounded-md border border-blue-400/10 outline-none cursor-pointer hover:bg-blue-400/20 transition-colors appearance-none"
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
          </div>

          <div className="flex items-center gap-8">
            <div className="flex items-center gap-8">
              <div className="flex flex-col items-end gap-0.5">
                <span className="text-[9px] font-black text-white/40 uppercase tracking-[0.2em]">Input</span>
                <span className="text-blue-400 font-mono text-xs font-bold">{currentUsage.input_tokens.toLocaleString()}</span>
              </div>
              <div className="flex flex-col items-end gap-0.5">
                <span className="text-[9px] font-black text-white/40 uppercase tracking-[0.2em]">Output</span>
                <span className="text-indigo-400 font-mono text-xs font-bold">{currentUsage.output_tokens.toLocaleString()}</span>
              </div>
              <div className="flex flex-col items-end gap-0.5 rounded-xl bg-white/5 px-4 py-1.5 border border-white/5">
                <span className="text-[9px] font-black text-white/60 uppercase tracking-[0.2em]">Total Tokens</span>
                <span className="text-white font-mono text-xs font-bold">{currentUsage.total_tokens.toLocaleString()}</span>
              </div>
            </div>
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
                    <div className="flex-1 flex flex-col items-center justify-center text-center space-y-6">
                      <div className="w-20 h-20 rounded-[2.5rem] bg-gradient-to-br from-white/5 to-white/[0.01] border border-white/10 flex items-center justify-center mb-2 shadow-2xl relative group">
                        <div className="absolute inset-0 bg-blue-500/10 rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity" />
                        <Terminal className="text-white/20 relative z-10" size={36} />
                      </div>
                      <div className="space-y-2">
                        <h2 className="text-3xl font-bold tracking-tighter bg-clip-text text-transparent bg-gradient-to-b from-white to-white/40">{t('chat.welcome_title')}</h2>
                        <p className="text-white/30 max-w-sm text-sm font-medium leading-relaxed italic">{t('chat.welcome_subtitle')}</p>
                      </div>
                      <div className="grid grid-cols-2 gap-3 max-w-md w-full pt-4">
                         <QuickAction onClick={() => setInput(t('chat.quick_actions.p1'))}>{t('chat.quick_actions.web_research')}</QuickAction>
                         <QuickAction onClick={() => setInput(t('chat.quick_actions.p2'))}>{t('chat.quick_actions.repo_analysis')}</QuickAction>
                      </div>
                    </div>
                ) : (
                  messages.map((msg, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: msg.role === 'user' ? 20 : -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      className={cn(
                        "max-w-[85%] rounded-2xl px-5 py-3 text-[13px] leading-relaxed shadow-lg font-medium",
                        msg.role === 'user' 
                          ? "ml-auto bg-blue-600 text-white shadow-blue-500/20 ring-1 ring-white/10" 
                          : "mr-auto bg-white/[0.03] border border-white/10 text-white/80 backdrop-blur-md"
                      )}
                    >
                      <Markdown content={msg.content} />
                    </motion.div>
                  ))
                )}
              </div>

              {/* Input Area */}
              <div className="p-10 pt-0">
                <div className="relative glass rounded-[2rem] p-1.5 shadow-2xl overflow-hidden group border border-white/5">
                  <div className="absolute inset-0 bg-gradient-to-r from-blue-600/5 via-blue-400/5 to-transparent opacity-0 group-focus-within:opacity-100 transition-opacity pointer-events-none" />
                  <div className="flex items-center gap-3 p-3">
                    <input 
                      type="text" 
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                      placeholder={t('chat.placeholder')} 
                      className="flex-1 bg-transparent border-none outline-none px-4 py-2 text-sm placeholder:text-white/10 font-medium tracking-tight"
                    />
                    <button 
                      onClick={handleSend}
                      className="w-12 h-12 rounded-2xl bg-blue-600 flex items-center justify-center hover:bg-blue-500 transition-all shadow-lg shadow-blue-600/30 active:scale-90 transform group/btn overflow-hidden relative"
                    >
                      <Send size={20} className="relative z-10" />
                      <div className="absolute inset-0 bg-gradient-to-tr from-white/20 to-transparent opacity-0 group-hover/btn:opacity-100 transition-opacity" />
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
                    <p className="text-sm text-white/30 font-medium">全系统异步任务生命周期管理</p>
                  </div>
                  <div className="flex items-center gap-3">
                     <div className="px-4 py-2 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                        <span className="text-[10px] font-bold text-blue-400 uppercase tracking-widest">{tasks.length} 活跃任务</span>
                     </div>
                  </div>
                </header>

                <div className="space-y-4">
                  {tasks.length === 0 ? (
                    <div className="p-32 text-center glass rounded-[3rem] border border-white/5">
                      <Activity size={48} className="mx-auto text-white/5 mb-6" />
                      <p className="text-white/20 font-bold uppercase tracking-widest text-sm">当前没有正在运行的任务</p>
                    </div>
                  ) : (
                    tasks.map(task => (
                      <div key={task.id} className="glass rounded-[2rem] p-8 border border-white/10 flex items-center gap-8 group hover:border-white/20 transition-all relative overflow-hidden">
                        <div className="absolute inset-0 bg-gradient-to-r from-white/[0.02] to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                        <div className={cn(
                          "w-14 h-14 rounded-2xl flex items-center justify-center shrink-0 shadow-2xl relative z-10",
                          task.status === 'running' ? "bg-blue-500/10 text-blue-500" :
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
                              task.status === 'running' ? "bg-blue-600 text-white" :
                              task.status === 'success' ? "bg-green-600/20 text-green-400 border border-green-500/20" :
                              "bg-white/10 text-white/40"
                            )}>
                              {t(`tasks.status.${task.status}`)}
                            </span>
                          </div>
                          
                          <div className="flex items-center gap-4 text-xs font-medium text-white/30 italic">
                             <span>ID: {task.id}</span>
                             <span>•</span>
                             <span>{task.progress || '正在初始化...'}</span>
                          </div>

                          {task.status === 'running' && (
                            <div className="pt-2">
                               <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                                  <motion.div 
                                    initial={{ width: 0 }}
                                    animate={{ width: '100%' }}
                                    transition={{ duration: 10, repeat: Infinity }}
                                    className="h-full bg-gradient-to-r from-blue-600 via-blue-400 to-blue-600 bg-[length:200%_100%] animate-gradient-x"
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
          ) : (
            <motion.div 
              key="settings"
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.98 }}
              className="flex-1 overflow-y-auto p-12 custom-scrollbar"
            >
              <div className="max-w-5xl mx-auto space-y-12 pb-20">
                {/* Master Model Selection (Simplified & Moved to Top) */}
                <section className="flex items-center justify-between glass rounded-3xl p-6 border border-white/10 shadow-xl mb-12">
                   <div className="flex items-center gap-4">
                     <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
                       <Cpu className="text-blue-400" size={20} />
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
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* Task Monitor panel (Right) */}
      <AnimatePresence>
        {tasks.length > 0 && (
          <motion.aside 
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 300, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            className="border-l border-white/5 bg-[#0a0a0a]/50 backdrop-blur-xl flex flex-col p-6 overflow-hidden"
          >
            <div className="flex items-center justify-between mb-8">
              <h3 className="font-bold text-sm uppercase tracking-widest text-white/40">{t('tasks.monitor_title')}</h3>
              <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
            </div>
            
            <div className="space-y-4">
              {tasks.map(task => (
                <div key={task.id} className="p-4 rounded-2xl bg-white/5 border border-white/10 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold truncate max-w-[180px]">{task.title}</span>
                    <span role="status" className={cn(
                      "text-[10px] px-2 py-0.5 rounded-full font-bold uppercase",
                      task.status === 'running' ? "bg-blue-500/20 text-blue-400" :
                      task.status === 'success' ? "bg-green-500/20 text-green-400" :
                      "bg-white/10 text-white/40"
                    )}>
                      {t(`tasks.status.${task.status}`)}
                    </span>
                  </div>
                  {task.status === 'running' && (
                    <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                      <motion.div 
                        initial={{ width: 0 }}
                        animate={{ width: '60%' }}
                        className="h-full bg-blue-500"
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  );
}

function NavItem({ icon, label, active = false, onClick }: { icon: React.ReactNode, label: string, active?: boolean, onClick?: () => void }) {
  return (
    <div 
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 px-4 py-3 rounded-2xl transition-all duration-200 cursor-pointer group",
        active ? "bg-blue-600/10 text-blue-400" : "text-white/40 hover:text-white hover:bg-white/5"
      )}
    >
      <div className={cn(
        "transition-transform duration-300 group-hover:scale-110",
        active ? "text-blue-400" : "text-white/40 group-hover:text-white"
      )}>
        {icon}
      </div>
      <span className="text-sm font-semibold flex-1">{label}</span>
      {active && <ChevronRight size={14} className="opacity-50" />}
    </div>
  );
}

function QuickAction({ children, onClick }: { children: ReactNode, onClick: () => void }) {
  return (
    <button 
      onClick={onClick}
      className="p-4 rounded-2xl bg-white/[0.02] border border-white/5 hover:bg-white/[0.05] hover:border-white/10 transition-all text-[11px] font-bold text-white/40 hover:text-white/80 uppercase tracking-widest flex items-center justify-between group"
    >
      {children}
      <ChevronRight size={14} className="opacity-0 group-hover:opacity-100 transition-opacity" />
    </button>
  );
}

function ProviderCard({ config, onSave, t }: { config: any, onSave: (apiKey: string, baseUrl: string) => void, t: any }) {
  const [apiKey, setApiKey] = useState(config.api_key || '');
  const [baseUrl, setBaseUrl] = useState(config.base_url || config.metadata.placeholder_base_url || '');
  const [isEditing, setIsEditing] = useState(false);

  return (
    <div className="glass rounded-[2.5rem] p-6 border border-white/5 space-y-6 relative overflow-hidden group min-h-[280px] flex flex-col">
      <div className="absolute inset-0 bg-gradient-to-br from-blue-500/[0.03] to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
      
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
                  setIsEditing(true);
               }}
               placeholder="sk-••••••••••••••••"
               className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-blue-500/30 transition-colors"
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
               className="w-full bg-white/[0.03] border border-white/5 rounded-xl py-3 pl-11 pr-4 text-xs font-mono outline-none focus:border-blue-500/30 transition-colors"
             />
          </div>
        </div>
      </div>

      <div className="mt-auto pt-4 relative z-10">
        <button
          onClick={() => {
            onSave(apiKey, baseUrl);
            setIsEditing(false);
          }}
          disabled={!isEditing && config.api_key === apiKey && config.base_url === baseUrl}
          className={cn(
            "w-full py-4 rounded-2xl text-[11px] font-bold uppercase tracking-widest shadow-lg flex items-center justify-center gap-2 group/save transition-all active:scale-[0.98]",
            isEditing || config.api_key !== apiKey || config.base_url !== baseUrl
              ? "bg-blue-600 text-white shadow-blue-500/20 hover:bg-blue-500" 
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
