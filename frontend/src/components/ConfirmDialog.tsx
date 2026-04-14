import { AlertTriangle } from 'lucide-react';
import { cn } from '../utils/cn';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  isBusy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  isBusy = false,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-6 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl border border-red-400/20 bg-[#0d0d0d] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-red-400/20 bg-red-500/10 text-red-200">
            <AlertTriangle size={18} />
          </div>
          <div className="space-y-2">
            <h3 className="text-base font-black tracking-tight text-white">{title}</h3>
            <p className="text-sm font-medium leading-6 text-white/55">{description}</p>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={isBusy}
            className="rounded-lg border border-white/10 bg-white/[0.03] px-4 py-2 text-xs font-bold text-white/65 transition-colors hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            disabled={isBusy}
            className={cn(
              'rounded-lg border px-4 py-2 text-xs font-black transition-colors',
              isBusy
                ? 'cursor-not-allowed border-red-400/10 bg-red-500/10 text-red-200/50'
                : 'border-red-400/25 bg-red-500/15 text-red-100 hover:bg-red-500/25'
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
