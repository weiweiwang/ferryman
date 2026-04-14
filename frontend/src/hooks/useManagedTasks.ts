import { useCallback, useState } from 'react';

export type ManagedTaskStatus = 'pending' | 'running' | 'success' | 'failed' | 'canceled';

export interface ManagedTask {
  id: string;
  session_id: string;
  parent_id: string | null;
  title: string;
  status: ManagedTaskStatus;
  progress?: string;
  instruction?: string;
  payload?: Record<string, any>;
  created_at?: string;
  updated_at: string;
  finished_at?: string | null;
}

export interface TaskSummary {
  pending: number;
  running: number;
  success: number;
  failed: number;
  canceled: number;
  total: number;
}

const PAGE_SIZE = 20;

const EMPTY_SUMMARY: TaskSummary = {
  pending: 0,
  running: 0,
  success: 0,
  failed: 0,
  canceled: 0,
  total: 0,
};

export function useManagedTasks(call: (method: string, params?: any) => Promise<any>) {
  const [tasks, setTasks] = useState<ManagedTask[]>([]);
  const [selectedTask, setSelectedTask] = useState<ManagedTask | null>(null);
  const [summary, setSummary] = useState<TaskSummary>(EMPTY_SUMMARY);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTasks = useCallback(async ({ append = false, cursor = null }: { append?: boolean; cursor?: string | null } = {}) => {
    append ? setIsLoadingMore(true) : setIsLoading(true);
    setError(null);
    try {
      const result: any = await call('list_tasks', { limit: PAGE_SIZE, cursor });
      const incoming = result?.tasks || [];
      setTasks((prev) => append ? [...prev, ...incoming] : incoming);
      setSummary(result?.summary || EMPTY_SUMMARY);
      setNextCursor(result?.next_cursor || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, [call]);

  const selectTask = useCallback(async (taskId: string) => {
    setError(null);
    try {
      const result: any = await call('get_task', { task_id: taskId });
      if (result?.status === 'error') {
        throw new Error(result.message);
      }
      setSelectedTask(result.task || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [call]);

  const updateTask = useCallback(async (task: ManagedTask) => {
    const result: any = await call('update_task', {
      task_id: task.id,
      title: task.title,
      status: task.status,
      progress_note: task.progress || '',
      instruction: task.instruction || '',
      payload: task.payload || {},
    });
    if (result?.status === 'error') {
      throw new Error(result.message);
    }
    await selectTask(task.id);
    await loadTasks();
  }, [call, loadTasks, selectTask]);

  const deleteTask = useCallback(async (taskId: string) => {
    const result: any = await call('delete_task', { task_id: taskId });
    if (result?.status === 'error') {
      throw new Error(result.message);
    }
    setSelectedTask(null);
    await loadTasks();
  }, [call, loadTasks]);

  return {
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
  };
}
