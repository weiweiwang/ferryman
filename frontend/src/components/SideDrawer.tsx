import { useEffect, type ReactNode } from 'react';
import { X } from 'lucide-react';

interface SideDrawerProps {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}

export function SideDrawer({ open, title, subtitle, onClose, children }: SideDrawerProps) {
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/35 backdrop-blur-[2px]" onClick={onClose}>
      <aside
        className="h-full w-full border-l border-white/10 bg-[#0b0b0b]/96 shadow-[-24px_0_80px_rgba(0,0,0,0.5)] sm:min-w-[420px] sm:max-w-[min(560px,46vw)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex h-full flex-col">
          <header className="flex items-start justify-between gap-4 border-b border-white/8 px-6 py-5">
            <div>
              <h3 className="text-xl font-black tracking-tight text-white">{title}</h3>
              {subtitle && <p className="mt-1 text-xs font-medium text-white/32">{subtitle}</p>}
            </div>
            <button
              onClick={onClose}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-white/45 transition-colors hover:bg-white/10 hover:text-white"
              aria-label="Close"
            >
              <X size={16} />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto p-6 custom-scrollbar">
            {children}
          </div>
        </div>
      </aside>
    </div>
  );
}
