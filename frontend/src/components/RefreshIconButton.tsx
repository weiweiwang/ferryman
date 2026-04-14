import { RefreshCw } from 'lucide-react';
import { cn } from '../utils/cn';

interface RefreshIconButtonProps {
  label: string;
  isLoading?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

export function RefreshIconButton({
  label,
  isLoading = false,
  disabled = false,
  onClick,
}: RefreshIconButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-white/65 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
    >
      <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
    </button>
  );
}
