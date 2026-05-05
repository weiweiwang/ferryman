import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { Check, Copy, RefreshCw } from 'lucide-react';
import { SideDrawer } from './SideDrawer';
import { cn } from '../utils/cn';

type UsageTotals = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
};

type DailyUsage = UsageTotals & {
  date: string;
  period_start_utc: string;
  period_end_utc: string;
};

type SessionInsights = {
  session_id: string;
  range: {
    key: RangeKey;
    timezone: string;
    start_date: string;
    end_date: string;
    start_utc: string;
    end_utc: string;
  };
  usage: {
    daily: DailyUsage[];
    range_totals: UsageTotals;
    session_totals: UsageTotals;
    archived_totals: UsageTotals;
    unattributed_system_usage: UsageTotals;
  };
  memory: Record<string, any> | null;
};

type RangeKey = 'today' | 'yesterday' | 'last_7_days' | 'last_30_days' | 'last_90_days';

const RANGE_KEYS: RangeKey[] = ['today', 'yesterday', 'last_7_days', 'last_30_days', 'last_90_days'];
const CHART_WIDTH = 760;
const CHART_HEIGHT = 250;
const CHART_TOP = 28;
const CHART_BOTTOM = 38;
const CHART_LEFT = 62;
const CHART_RIGHT = 62;

interface SessionInsightsDrawerProps {
  open: boolean;
  sessionId: string;
  isConnected: boolean;
  call: (method: string, params?: any) => Promise<any>;
  onClose: () => void;
  t: (key: string) => string;
}

function formatNumber(value: number) {
  return Math.round(value || 0).toLocaleString();
}

function formatShortNumber(value: number) {
  const abs = Math.abs(value || 0);
  if (abs >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(abs >= 10_000_000 ? 1 : 2)}M`;
  }
  if (abs >= 1_000) {
    return `${(value / 1_000).toFixed(abs >= 10_000 ? 1 : 2)}K`;
  }
  return String(Math.round(value || 0));
}

function formatDateLabel(date: string) {
  const parts = date.split('-');
  if (parts.length !== 3) {
    return date;
  }
  return `${parts[1]}/${parts[2]}`;
}

function buildLinePath(points: Array<{ x: number; y: number }>) {
  if (points.length === 0) {
    return '';
  }
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ');
}

function buildTicks(maxValue: number) {
  const normalizedMax = Math.max(1, maxValue);
  return [0, 1, 2, 3, 4].map((step) => Math.round((normalizedMax * step) / 4));
}

function mapChartY(value: number, maxValue: number) {
  const usableHeight = CHART_HEIGHT - CHART_TOP - CHART_BOTTOM;
  return CHART_TOP + usableHeight - ((value || 0) / Math.max(1, maxValue)) * usableHeight;
}

function buildChartModel(daily: DailyUsage[]) {
  const leftMax = Math.max(1, ...daily.flatMap((item) => [item.input_tokens, item.total_tokens]));
  const rightMax = Math.max(1, ...daily.map((item) => item.output_tokens));
  const usableWidth = CHART_WIDTH - CHART_LEFT - CHART_RIGHT;
  const step = daily.length > 1 ? usableWidth / (daily.length - 1) : 0;
  const xForIndex = (index: number) => CHART_LEFT + (daily.length > 1 ? step * index : usableWidth / 2);
  const inputPoints = daily.map((item, index) => ({
    x: xForIndex(index),
    y: mapChartY(item.input_tokens, leftMax),
    item,
  }));
  const totalPoints = daily.map((item, index) => ({
    x: xForIndex(index),
    y: mapChartY(item.total_tokens, leftMax),
    item,
  }));
  const outputPoints = daily.map((item, index) => ({
    x: xForIndex(index),
    y: mapChartY(item.output_tokens, rightMax),
    item,
  }));

  return {
    leftMax,
    rightMax,
    inputPoints,
    outputPoints,
    totalPoints,
    inputPath: buildLinePath(inputPoints),
    outputPath: buildLinePath(outputPoints),
    totalPath: buildLinePath(totalPoints),
    leftTicks: buildTicks(leftMax),
    rightTicks: buildTicks(rightMax),
  };
}

function EmptySkeleton() {
  return (
    <div className="space-y-3">
      <div className="h-5 w-36 animate-pulse rounded-md bg-white/8" />
      <div className="h-48 animate-pulse rounded-xl border border-white/8 bg-white/[0.035]" />
      <div className="grid grid-cols-3 gap-3">
        <div className="h-16 animate-pulse rounded-xl bg-white/[0.035]" />
        <div className="h-16 animate-pulse rounded-xl bg-white/[0.035]" />
        <div className="h-16 animate-pulse rounded-xl bg-white/[0.035]" />
      </div>
    </div>
  );
}

function StatTile({ label, value, tone = 'default' }: { label: string; value: number; tone?: 'default' | 'bright' }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.035] px-4 py-3">
      <div className="text-[10px] font-black uppercase tracking-widest text-white/35">{label}</div>
      <div className={cn("mt-2 font-mono text-lg font-bold", tone === 'bright' ? "text-white" : "text-white/72")}>
        {formatNumber(value)}
      </div>
    </div>
  );
}

export function SessionInsightsDrawer({
  open,
  sessionId,
  isConnected,
  call,
  onClose,
  t,
}: SessionInsightsDrawerProps) {
  const [rangeKey, setRangeKey] = useState<RangeKey>('last_30_days');
  const [insights, setInsights] = useState<SessionInsights | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [isSummaryCopied, setIsSummaryCopied] = useState(false);

  useEffect(() => {
    if (!open || !isConnected || !sessionId) {
      return;
    }

    let cancelled = false;
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    setIsLoading(true);
    setError(null);
    call('get_session_insights', { session_id: sessionId, range_key: rangeKey, timezone })
      .then((result) => {
        if (!cancelled) {
          setInsights(result as SessionInsights);
        }
      })
      .catch((loadError) => {
        console.error('Failed to load session insights:', loadError);
        if (!cancelled) {
          setError(t('insights.load_failed'));
          setInsights(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [call, isConnected, open, rangeKey, sessionId, t]);

  const chartModel = useMemo(() => {
    return buildChartModel(insights?.usage.daily || []);
  }, [insights]);

  const compaction = insights?.memory?.compaction;
  const summary = typeof compaction?.summary === 'string' ? compaction.summary : '';
  const summaryTokenEstimate = Number(compaction?.summary_token_estimate || 0);
  const unattributed = insights?.usage.unattributed_system_usage.total_tokens || 0;
  const hoveredPoint = hoverIndex === null ? null : chartModel.totalPoints[hoverIndex];

  const handleChartMouseMove = (event: MouseEvent<SVGSVGElement>) => {
    const daily = insights?.usage.daily || [];
    if (daily.length === 0) {
      return;
    }

    const bounds = event.currentTarget.getBoundingClientRect();
    const viewBoxX = ((event.clientX - bounds.left) / bounds.width) * CHART_WIDTH;
    const usableWidth = CHART_WIDTH - CHART_LEFT - CHART_RIGHT;
    const step = daily.length > 1 ? usableWidth / (daily.length - 1) : usableWidth;
    const nextIndex = daily.length > 1 ? Math.round((viewBoxX - CHART_LEFT) / step) : 0;
    setHoverIndex(Math.min(daily.length - 1, Math.max(0, nextIndex)));
  };

  const handleCopySummary = async () => {
    if (!summary) {
      return;
    }

    try {
      await navigator.clipboard.writeText(summary);
      setIsSummaryCopied(true);
      window.setTimeout(() => setIsSummaryCopied(false), 1600);
    } catch (copyError) {
      console.error('Failed to copy compaction summary:', copyError);
    }
  };

  return (
    <SideDrawer
      open={open}
      title={t('insights.title')}
      subtitle={t('insights.subtitle')}
      onClose={onClose}
      size="wide"
    >
      <div className="space-y-6">
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h4 className="text-sm font-black tracking-tight text-white">{t('insights.usage_title')}</h4>
              <p className="mt-1 text-xs font-medium text-white/35">{insights?.range.timezone || t('common.loading')}</p>
            </div>
            <div className="flex rounded-xl border border-white/10 bg-white/[0.035] p-1">
              {RANGE_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setRangeKey(key)}
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-[11px] font-bold transition-colors",
                    rangeKey === key ? "bg-white text-[#080808]" : "text-white/45 hover:bg-white/8 hover:text-white/75"
                  )}
                >
                  {t(`insights.ranges.${key}`)}
                </button>
              ))}
            </div>
          </div>

          {isLoading && !insights ? (
            <EmptySkeleton />
          ) : error ? (
            <div className="rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm font-medium text-red-100">
              {error}
            </div>
          ) : (
            <>
              <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <Legend color="bg-sky-300" label={t('tasks.token_in')} />
                    <Legend color="bg-emerald-300" label={t('tasks.token_out')} />
                    <Legend color="bg-white" label={t('tasks.token_total')} />
                  </div>
                  {isLoading ? <RefreshCw size={14} className="animate-spin text-white/35" /> : null}
                </div>
                <svg
                  viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
                  className="mt-3 h-64 w-full overflow-visible"
                  onMouseMove={handleChartMouseMove}
                  onMouseLeave={() => setHoverIndex(null)}
                >
                  <defs>
                    <linearGradient id="totalUsageGlow" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="rgba(255,255,255,0.18)" />
                      <stop offset="100%" stopColor="rgba(255,255,255,0)" />
                    </linearGradient>
                  </defs>
                  {chartModel.leftTicks.map((tick, index) => {
                    const y = mapChartY(tick, chartModel.leftMax);
                    const rightTick = Math.round((chartModel.rightMax * tick) / chartModel.leftMax);
                    return (
                      <g key={`${tick}-${index}`}>
                        <line x1={CHART_LEFT} x2={CHART_WIDTH - CHART_RIGHT} y1={y} y2={y} stroke="rgba(255,255,255,0.08)" />
                        <text x={CHART_LEFT - 10} y={y + 4} textAnchor="end" fill="rgba(125,211,252,0.58)" fontSize="10" fontWeight="700">
                          {formatShortNumber(tick)}
                        </text>
                        <text x={CHART_WIDTH - CHART_RIGHT + 10} y={y + 4} textAnchor="start" fill="rgba(110,231,183,0.58)" fontSize="10" fontWeight="700">
                          {formatShortNumber(rightTick)}
                        </text>
                      </g>
                    );
                  })}
                  <text x={CHART_LEFT} y={12} textAnchor="start" fill="rgba(125,211,252,0.62)" fontSize="10" fontWeight="800">
                    {t('tasks.token_in')} / {t('tasks.token_total')}
                  </text>
                  <text x={CHART_WIDTH - CHART_RIGHT} y={12} textAnchor="end" fill="rgba(110,231,183,0.62)" fontSize="10" fontWeight="800">
                    {t('tasks.token_out')}
                  </text>
                  {chartModel.totalPath ? (
                    <>
                      <path d={chartModel.totalPath} fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                      <path d={chartModel.inputPath} fill="none" stroke="rgba(125,211,252,0.9)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      <path d={chartModel.outputPath} fill="none" stroke="rgba(110,231,183,0.9)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      {chartModel.totalPoints.map((point, index) => (
                        <g key={point.item.date}>
                          <circle cx={chartModel.inputPoints[index].x} cy={chartModel.inputPoints[index].y} r={hoverIndex === index ? 4 : 2.5} fill="rgb(125,211,252)">
                            <title>{`${point.item.date} ${t('tasks.input_tokens')}: ${formatNumber(point.item.input_tokens)}`}</title>
                          </circle>
                          <circle cx={chartModel.outputPoints[index].x} cy={chartModel.outputPoints[index].y} r={hoverIndex === index ? 4 : 2.5} fill="rgb(110,231,183)">
                            <title>{`${point.item.date} ${t('tasks.output_tokens')}: ${formatNumber(point.item.output_tokens)}`}</title>
                          </circle>
                        </g>
                      ))}
                      {hoveredPoint ? (
                        <g>
                          <line x1={hoveredPoint.x} x2={hoveredPoint.x} y1={CHART_TOP} y2={CHART_HEIGHT - CHART_BOTTOM} stroke="rgba(255,255,255,0.18)" strokeDasharray="4 4" />
                          {(() => {
                            const tooltipWidth = 164;
                            const tooltipHeight = 76;
                            const tooltipX = Math.min(CHART_WIDTH - CHART_RIGHT - tooltipWidth, Math.max(CHART_LEFT, hoveredPoint.x + 12));
                            const tooltipY = Math.max(CHART_TOP, Math.min(CHART_HEIGHT - CHART_BOTTOM - tooltipHeight, hoveredPoint.y - 38));
                            return (
                              <g>
                                <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx="10" fill="rgba(10,10,10,0.92)" stroke="rgba(255,255,255,0.16)" />
                                <text x={tooltipX + 12} y={tooltipY + 18} fill="rgba(255,255,255,0.88)" fontSize="11" fontWeight="800">{hoveredPoint.item.date}</text>
                                <text x={tooltipX + 12} y={tooltipY + 36} fill="rgb(125,211,252)" fontSize="10" fontWeight="700">{t('tasks.input_tokens')}: {formatNumber(hoveredPoint.item.input_tokens)}</text>
                                <text x={tooltipX + 12} y={tooltipY + 52} fill="rgb(110,231,183)" fontSize="10" fontWeight="700">{t('tasks.output_tokens')}: {formatNumber(hoveredPoint.item.output_tokens)}</text>
                                <text x={tooltipX + 12} y={tooltipY + 68} fill="rgba(255,255,255,0.86)" fontSize="10" fontWeight="800">{t('tasks.total_tokens')}: {formatNumber(hoveredPoint.item.total_tokens)}</text>
                              </g>
                            );
                          })()}
                        </g>
                      ) : null}
                    </>
                  ) : (
                    <text x={CHART_WIDTH / 2} y={CHART_HEIGHT / 2} textAnchor="middle" fill="rgba(255,255,255,0.32)" fontSize="14" fontWeight="700">
                      {t('insights.no_usage')}
                    </text>
                  )}
                </svg>
                <div className="flex items-center justify-between gap-2 overflow-hidden px-1 text-[10px] font-bold text-white/28">
                  {(insights?.usage.daily || []).filter((_, index, items) => (
                    items.length <= 8 || index === 0 || index === items.length - 1 || index % Math.ceil(items.length / 5) === 0
                  )).map((item) => (
                    <span key={item.date}>{formatDateLabel(item.date)}</span>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <StatTile label={t('tasks.input_tokens')} value={insights?.usage.range_totals.input_tokens || 0} />
                <StatTile label={t('tasks.output_tokens')} value={insights?.usage.range_totals.output_tokens || 0} />
                <StatTile label={t('tasks.total_tokens')} value={insights?.usage.range_totals.total_tokens || 0} tone="bright" />
              </div>

              {unattributed > 0 ? (
                <div className="rounded-xl border border-amber-300/15 bg-amber-300/[0.06] px-4 py-3 text-xs font-medium leading-5 text-amber-100/72">
                  {t('insights.unattributed_prefix')} {formatShortNumber(unattributed)} {t('tasks.tokens_unit')}
                </div>
              ) : null}
            </>
          )}
        </section>

        <section className="space-y-4 border-t border-white/8 pt-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h4 className="text-sm font-black tracking-tight text-white">{t('insights.memory_title')}</h4>
              <p className="mt-1 text-xs font-medium text-white/35">{t('insights.memory_subtitle')}</p>
            </div>
          </div>

          {!insights?.memory ? (
            <div className="rounded-2xl border border-white/8 bg-white/[0.025] px-5 py-8 text-center text-sm font-medium text-white/35">
              {t('insights.no_memory')}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-white/35">
                    {t('insights.compaction_summary')}
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="rounded-lg border border-white/8 bg-white/[0.04] px-2.5 py-1 font-mono text-[11px] font-bold text-white/55">
                      ~{formatNumber(summaryTokenEstimate)} {t('tasks.tokens_unit')}
                    </div>
                    <button
                      type="button"
                      onClick={handleCopySummary}
                      disabled={!summary}
                      className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.035] text-white/50 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-45"
                      aria-label={isSummaryCopied ? t('common.copied') : t('common.copy')}
                      title={isSummaryCopied ? t('common.copied') : t('common.copy')}
                    >
                      {isSummaryCopied ? <Check size={15} /> : <Copy size={15} />}
                    </button>
                  </div>
                </div>
                <div className="mt-4 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-xl bg-black/20 p-4 text-sm leading-6 text-white/72 custom-scrollbar">
                  {summary || t('insights.empty_summary')}
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <MemoryMeta label={t('insights.cutoff')} value={compaction?.cutoff_created_at} />
                <MemoryMeta label={t('insights.updated_at')} value={compaction?.updated_at} />
              </div>
            </div>
          )}
        </section>
      </div>
    </SideDrawer>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-white/40">
      <span className={cn("h-2 w-2 rounded-full", color)} />
      {label}
    </div>
  );
}

function MemoryMeta({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.035] px-4 py-3">
      <div className="text-[10px] font-black uppercase tracking-widest text-white/32">{label}</div>
      <div className="mt-2 break-words font-mono text-[11px] font-bold leading-5 text-white/58">{value || '-'}</div>
    </div>
  );
}
