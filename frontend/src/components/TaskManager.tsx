import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Activity, Check, ChevronRight, Save, Trash2, X } from 'lucide-react';
import { ConfirmDialog } from './ConfirmDialog';
import { RefreshIconButton } from './RefreshIconButton';
import { SideDrawer } from './SideDrawer';
import { ManagedTask, ManagedTaskStatus, useManagedTasks } from '../hooks/useManagedTasks';
import { cn } from '../utils/cn';

interface TaskManagerProps {
  call: (method: string, params?: any) => Promise<any>;
  isConnected: boolean;
  t: (key: string) => string;
}

const STATUS_OPTIONS: ManagedTaskStatus[] = ['pending', 'running', 'success', 'failed', 'canceled'];

function formatDate(value?: string | null) {
  if (!value) return '-';
  return new Intl.DateTimeFormat(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

export function TaskManager({ call, isConnected, t }: TaskManagerProps) {
  const {
    tasks,
    selectedTask,
    setSelectedTask,
    summary,
    nextCursor,
    isLoading,
    isLoadingMore,
    error,
    loadTasks,
    selectTask,
    updateTask,
    deleteTask,
  } = useManagedTasks(call);
  const [draft, setDraft] = useState<ManagedTask | null>(null);
  const [payloadJson, setPayloadJson] = useState('{}');
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ManagedTask | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (isConnected) {
      loadTasks();
    }
  }, [isConnected, loadTasks]);

  useEffect(() => {
    setDraft(selectedTask);
    setPayloadJson(JSON.stringify(selectedTask?.payload || {}, null, 2));
    setFormError(null);
  }, [selectedTask]);

  const summaryItems = useMemo(() => [
    { key: 'pending', value: summary.pending, className: 'text-amber-300' },
    { key: 'running', value: summary.running, className: 'text-white' },
    { key: 'success', value: summary.success, className: 'text-green-300' },
    { key: 'failed', value: summary.failed, className: 'text-red-300' },
    { key: 'canceled', value: summary.canceled, className: 'text-white/45' },
    { key: 'total', value: summary.total, className: 'text-white' },
  ], [summary]);

  const handleSave = async () => {
    if (!draft) return;
    setIsSaving(true);
    setFormError(null);
    try {
      const payload = payloadJson.trim() ? JSON.parse(payloadJson) : {};
      await updateTask({ ...draft, payload });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    setFormError(null);
    try {
      await deleteTask(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="flex-1 overflow-hidden p-8">
      <div className="mx-auto flex h-full max-w-6xl flex-col gap-6">
        <header className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-4xl font-black tracking-tight">{t('tasks.title')}</h2>
            <p className="mt-2 text-sm font-medium text-white/32">{t('tasks.subtitle')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {summaryItems.map((item) => (
              <div key={item.key} className="rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2">
                <span className={cn('mr-2 text-sm font-black tabular-nums', item.className)}>{item.value}</span>
                <span className="text-[9px] font-black uppercase tracking-[0.18em] text-white/35">
                  {item.key === 'total' ? t('tasks.total_count') : t(`tasks.status.${item.key}`)}
                </span>
              </div>
            ))}
            <RefreshIconButton
              onClick={() => loadTasks()}
              disabled={!isConnected || isLoading}
              isLoading={isLoading}
              label={t('tasks.refresh')}
            />
          </div>
        </header>

        <section className="min-h-0 flex-1 overflow-hidden rounded-xl border border-white/8 bg-white/[0.02]">
          <div className="flex h-full flex-col">
            <div className="grid grid-cols-[minmax(0,1fr)_120px_120px_32px] items-center gap-3 border-b border-white/8 px-5 py-3 text-[10px] font-black uppercase tracking-[0.18em] text-white/28">
              <span>{t('tasks.list_title')}</span>
              <span>{t('tasks.field_status')}</span>
              <span>{t('tasks.field_updated_at')}</span>
              <span />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
              {error && <div className="m-4 rounded-lg border border-red-400/20 bg-red-500/10 p-3 text-xs text-red-100">{error}</div>}
              {tasks.length === 0 && !isLoading ? (
                <div className="flex h-full flex-col items-center justify-center p-10 text-center">
                  <Activity size={34} className="mb-4 text-white/8" />
                  <p className="text-sm font-bold text-white/25">{t('tasks.empty')}</p>
                </div>
              ) : (
                tasks.map((task) => (
                  <button
                    key={task.id}
                    onClick={() => selectTask(task.id)}
                    className={cn(
                      'group grid min-h-[72px] w-full grid-cols-[minmax(0,1fr)_120px_120px_32px] items-center gap-3 border-b border-white/6 px-5 py-3 text-left transition-colors hover:bg-white/[0.045]',
                      selectedTask?.id === task.id && 'bg-white/[0.055]'
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-4">
                      <TaskStatusIcon status={task.status} />
                      <div className="min-w-0 flex-1">
                        <h3 className="truncate text-sm font-black tracking-tight text-white/84">{task.title}</h3>
                        <p className="mt-1 truncate text-xs font-medium text-white/32">{task.progress || t('tasks.no_progress')}</p>
                      </div>
                    </div>
                    <span className="w-fit rounded-md border border-white/10 px-2 py-1 text-[9px] font-black uppercase tracking-[0.14em] text-white/42">
                      {t(`tasks.status.${task.status}`)}
                    </span>
                    <span className="font-mono text-[10px] text-white/28">{formatDate(task.updated_at)}</span>
                    <ChevronRight size={15} className="justify-self-end text-white/18 transition-transform group-hover:translate-x-0.5 group-hover:text-white/45" />
                  </button>
                ))
              )}
            </div>
            {nextCursor && (
              <button
                onClick={() => loadTasks({ append: true, cursor: nextCursor })}
                disabled={isLoadingMore}
                className="border-t border-white/8 px-4 py-3 text-xs font-black uppercase tracking-[0.18em] text-white/45 transition-colors hover:bg-white/[0.04] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {isLoadingMore ? t('common.loading') : t('common.load_more')}
              </button>
            )}
          </div>
        </section>
      </div>

      <SideDrawer
        open={Boolean(draft)}
        title={t('tasks.detail_title')}
        subtitle={draft ? formatDate(draft.updated_at) : undefined}
        onClose={() => setSelectedTask(null)}
      >
        {draft && (
          <div className="space-y-5">
            <Field label={t('tasks.field_title')}>
              <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} className="field-input" />
            </Field>
            <Field label={t('tasks.field_status')}>
              <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as ManagedTaskStatus })} className="field-input">
                {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{t(`tasks.status.${status}`)}</option>)}
              </select>
            </Field>
            <Field label={t('tasks.field_progress')}>
              <textarea
                value={draft.progress || ''}
                onChange={(event) => setDraft({ ...draft, progress: event.target.value })}
                className="field-textarea min-h-[96px]"
              />
            </Field>
            <Field label={t('tasks.field_instruction')}>
              <textarea value={draft.instruction || ''} onChange={(event) => setDraft({ ...draft, instruction: event.target.value })} className="field-textarea min-h-[120px]" />
            </Field>
            <Field label={t('tasks.field_payload')}>
              <textarea value={payloadJson} onChange={(event) => setPayloadJson(event.target.value)} className="field-textarea min-h-[140px] font-mono text-[11px]" />
            </Field>
            <div className="grid grid-cols-2 gap-3 text-xs text-white/35">
              <Meta label={t('tasks.field_created_at')} value={formatDate(draft.created_at)} />
              <Meta label={t('tasks.field_finished_at')} value={formatDate(draft.finished_at)} />
              <Meta label={t('tasks.identifier')} value={draft.id} wide />
            </div>
            {formError && <p className="rounded-lg border border-red-400/20 bg-red-500/10 p-3 text-xs text-red-100">{formError}</p>}
            <div className="flex items-center justify-between gap-3 border-t border-white/8 pt-5">
              <button onClick={() => setDeleteTarget(draft)} className="inline-flex items-center gap-2 rounded-lg border border-red-400/20 px-4 py-2 text-xs font-black text-red-200 transition-colors hover:bg-red-500/15">
                <Trash2 size={14} />
                {t('common.delete')}
              </button>
              <button onClick={handleSave} disabled={isSaving} className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-xs font-black text-[#080808] transition-colors hover:bg-white/90 disabled:cursor-not-allowed disabled:opacity-50">
                <Save size={14} />
                {isSaving ? t('common.saving') : t('common.save')}
              </button>
            </div>
          </div>
        )}
      </SideDrawer>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={t('tasks.delete_title')}
        description={t('tasks.delete_description').replace('{name}', deleteTarget?.title || '')}
        confirmLabel={t('tasks.confirm_delete')}
        cancelLabel={t('common.cancel')}
        isBusy={isDeleting}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}

function TaskStatusIcon({ status }: { status: ManagedTaskStatus }) {
  const iconClass = status === 'success' ? 'text-green-300' : status === 'failed' ? 'text-red-300' : status === 'pending' ? 'text-amber-300' : 'text-white/65';
  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-black/20">
      {status === 'success' ? <Check size={15} className={iconClass} /> : status === 'failed' ? <X size={15} className={iconClass} /> : <Activity size={15} className={cn(iconClass, status === 'running' && 'animate-spin-slow')} />}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="text-[10px] font-black uppercase tracking-[0.2em] text-white/30">{label}</span>
      {children}
    </label>
  );
}

function Meta({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn('rounded-lg border border-white/8 bg-black/15 p-3', wide && 'col-span-2')}>
      <div className="mb-1 text-[9px] font-black uppercase tracking-[0.18em] text-white/25">{label}</div>
      <div className="break-all font-mono text-[11px] text-white/55">{value}</div>
    </div>
  );
}
