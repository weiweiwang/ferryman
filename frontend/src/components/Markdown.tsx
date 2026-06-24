import { useEffect, useRef, useState } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { invoke } from '@tauri-apps/api/core';
import { Check, Copy } from 'lucide-react';

import { useI18n } from '../hooks/useI18n';
import { cn } from '../utils/cn';

interface MarkdownProps {
  content: string;
}

const SAFE_RED_SPAN_PATTERN = /<span\b(?=[^>]*\bstyle\s*=\s*(['"])[^'"]*\bcolor\s*:\s*red\b[^'"]*\1)[^>]*>([\s\S]*?)<\/span>/gi;
const FENCED_CODE_BLOCK_PATTERN = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g;
const SAFE_RED_LINK_HREF = 'ferryman-red:';

function escapeMarkdownLinkLabel(value: string) {
  return value.replace(/\\/g, '\\\\').replace(/]/g, '\\]');
}

function replaceSafeInlineHtml(value: string) {
  return value.replace(SAFE_RED_SPAN_PATTERN, (_match, _quote, inner) => {
    return `[${escapeMarkdownLinkLabel(inner)}](${SAFE_RED_LINK_HREF})`;
  });
}

function normalizeSafeInlineHtml(content: string) {
  return content
    .split(FENCED_CODE_BLOCK_PATTERN)
    .map((part) => part.startsWith('```') || part.startsWith('~~~') ? part : replaceSafeInlineHtml(part))
    .join('');
}

function CopyCodeButton({ text, t }: { text: string; t: (key: string) => string }) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);

      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }

      resetTimerRef.current = window.setTimeout(() => {
        setCopied(false);
      }, 1800);
    } catch (error) {
      console.error('Failed to copy code block:', error);
    }
  };

  return (
    <button
      type="button"
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        void handleCopy();
      }}
      aria-label={copied ? t('common.copied') : t('common.copy')}
      title={copied ? t('common.copied') : t('common.copy')}
      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-black/45 text-white/60 backdrop-blur-md transition-colors hover:border-white/20 hover:text-white"
    >
      {copied ? <Check size={14} strokeWidth={2.4} /> : <Copy size={14} strokeWidth={2.1} />}
    </button>
  );
}

export const Markdown = ({ content }: MarkdownProps) => {
  const { t } = useI18n();

  const isAbsoluteLocalPath = (value?: string) => {
    return Boolean(value && (value.startsWith('/') || /^[a-zA-Z]:(?:\\|\/)/.test(value)));
  };

  return (
    <div className="prose prose-invert max-w-none [overflow-wrap:anywhere] prose-p:leading-relaxed prose-pre:bg-[#0d0d0d] prose-pre:border prose-pre:border-white/5 prose-code:text-blue-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => {
          if (url === SAFE_RED_LINK_HREF) {
            return url;
          }
          if (url.startsWith('file://')) {
            return url;
          }
          return defaultUrlTransform(url);
        }}
        components={{
        table({ node, className, children, ...props }: any) {
          return (
            <div className="my-5 w-fit max-w-full overflow-x-auto rounded-xl border border-white/10 bg-white/[0.025] [overflow-wrap:normal]">
              <table className={cn("w-max border-collapse text-left text-[0.95em] leading-6", className)} {...props}>
                {children}
              </table>
            </div>
          );
        },
        thead({ node, className, children, ...props }: any) {
          return (
            <thead className={cn("bg-white/[0.06] text-white", className)} {...props}>
              {children}
            </thead>
          );
        },
        th({ node, className, children, ...props }: any) {
          return (
            <th
              className={cn(
                "whitespace-nowrap border-b border-white/12 px-3 py-2.5 text-sm font-black text-white",
                className
              )}
              {...props}
            >
              {children}
            </th>
          );
        },
        td({ node, className, children, ...props }: any) {
          return (
            <td
              className={cn(
                "border-t border-white/[0.06] px-3 py-2.5 align-top text-white/78 first:whitespace-nowrap",
                className
              )}
              {...props}
            >
              {children}
            </td>
          );
        },
        code({ node, inline, className, children, ...props }: any) {
          const match = /language-(\w+)/.exec(className || '');
          // Deep extract string from React children array if needed.
          let text = '';
          if (Array.isArray(children)) {
            text = children.map(c => typeof c === 'string' ? c : '').join('');
          } else {
            text = String(children || '');
          }
          text = text.replace(/^\s+|\s+$/g, ''); // Trim all leading/trailing whitespace including newlines

          const isAbsolutePath = text.startsWith('/') || /^[a-zA-Z]:(?:\\|\/)/.test(text);

          if (isAbsolutePath) {
            return (
              <span 
                className="bg-white/10 px-1.5 py-0.5 rounded text-blue-400 hover:text-blue-300 font-mono text-[0.9em] cursor-pointer hover:underline transition-colors" 
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  invoke('open_local_file', { path: text }).catch(err => {
                    console.error("Failed native open:", err);
                  });
                }}
                title={`点击打开文件: ${text}`}
              >
                {children}
              </span>
            );
          }

          if (!inline) {
            return (
              <div className="group/code relative my-4 [overflow-wrap:normal]">
                <div className="absolute right-3 top-3 z-10 opacity-0 transition-opacity duration-150 group-hover/code:opacity-100 group-focus-within/code:opacity-100">
                  <CopyCodeButton text={text} t={t} />
                </div>
                <SyntaxHighlighter
                  style={vscDarkPlus as any}
                  language={match?.[1] || 'text'}
                  PreTag="div"
                  className="rounded-xl !my-0 border border-white/5"
                  customStyle={{
                    margin: 0,
                    borderRadius: '0.75rem',
                    background: '#0d0d0d',
                  }}
                  {...props}
                >
                  {text}
                </SyntaxHighlighter>
              </div>
            );
          }

          return (
            <code className="bg-white/10 px-1.5 py-0.5 rounded text-blue-300 font-mono text-[0.9em]" {...props}>
              {children}
            </code>
          );
        },
        a({ node, children, href, ...props }: any) {
          if (href === SAFE_RED_LINK_HREF) {
            return (
              <span className="font-semibold text-red-300 [&_strong]:text-red-200">
                {children}
              </span>
            );
          }

          const isFileUrl = href?.startsWith('file://');
          const isLocalPath = isAbsoluteLocalPath(href);
          if (isFileUrl || isLocalPath) {
            const rawPath = isFileUrl ? href.replace('file://', '') : href;
            // Handle local file path decoding and normalization
            const decodedPath = decodeURIComponent(rawPath);
            // On Windows, the path might look like /C:/User...
            const cleanPath = decodedPath.replace(/^\/([a-zA-Z]:)/, '$1');
            
            return (
              <a 
                {...props}
                className="cursor-pointer break-words text-blue-400 underline transition-colors [overflow-wrap:anywhere] hover:text-blue-300"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  invoke('open_local_file', { path: cleanPath }).catch(err => {
                    console.error("Failed native open:", err);
                  });
                }}
              >
                {children}
              </a>
            );
          }
          return <a className="break-words text-blue-400 underline transition-colors [overflow-wrap:anywhere] hover:text-blue-300" target="_blank" rel="noopener noreferrer" href={href} {...props}>{children}</a>;
        }

      }}
    >
      {normalizeSafeInlineHtml(content)}
    </ReactMarkdown>
    </div>
  );
};
