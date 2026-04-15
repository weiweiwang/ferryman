import { useCallback, useState } from 'react';

export interface Schedule {
  id: string;
  name: string;
  cron: string;
  timezone: string;
  enabled: boolean;
  instruction?: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  total_run_count: number;
  last_run_result?: {
    status: 'success' | 'failed';
    summary?: string | null;
    error?: string | null;
    run_id?: string | null;
    finished_at?: string | null;
  } | null;
  created_at?: string;
  updated_at: string;
}

const PAGE_SIZE = 20;

export function useSchedules(call: (method: string, params?: any) => Promise<any>) {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSchedules = useCallback(async ({ append = false, cursor = null }: { append?: boolean; cursor?: string | null } = {}) => {
    append ? setIsLoadingMore(true) : setIsLoading(true);
    setError(null);
    try {
      const result: any = await call('list_schedules', { limit: PAGE_SIZE, cursor });
      const incoming = result?.schedules || [];
      setSchedules((prev) => append ? [...prev, ...incoming] : incoming);
      setNextCursor(result?.next_cursor || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, [call]);

  const selectSchedule = useCallback(async (scheduleId: string) => {
    setError(null);
    try {
      const result: any = await call('get_schedule', { schedule_id: scheduleId });
      if (result?.status === 'error') {
        throw new Error(result.message);
      }
      setSelectedSchedule(result.schedule || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [call]);

  const updateSchedule = useCallback(async (schedule: Schedule) => {
    const result: any = await call('update_schedule', {
      schedule_id: schedule.id,
      name: schedule.name,
      cron: schedule.cron,
      timezone: schedule.timezone,
      enabled: schedule.enabled,
      instruction: schedule.instruction || '',
    });
    if (result?.status === 'error') {
      throw new Error(result.message);
    }
    await selectSchedule(schedule.id);
    await loadSchedules();
  }, [call, loadSchedules, selectSchedule]);

  const deleteSchedule = useCallback(async (scheduleId: string) => {
    const result: any = await call('delete_schedule', { schedule_id: scheduleId });
    if (result?.status === 'error') {
      throw new Error(result.message);
    }
    setSelectedSchedule(null);
    await loadSchedules();
  }, [call, loadSchedules]);

  return {
    schedules,
    selectedSchedule,
    setSelectedSchedule,
    nextCursor,
    isLoading,
    isLoadingMore,
    error,
    loadSchedules,
    selectSchedule,
    updateSchedule,
    deleteSchedule,
  };
}
