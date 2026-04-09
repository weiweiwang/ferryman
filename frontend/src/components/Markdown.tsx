import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { invoke } from '@tauri-apps/api/core';

interface MarkdownProps {
  content: string;
}

export const Markdown = ({ content }: MarkdownProps) => {
  return (
    <div className="prose prose-invert max-w-none prose-p:leading-relaxed prose-pre:bg-[#0d0d0d] prose-pre:border prose-pre:border-white/5 prose-code:text-blue-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
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
                  alert("准备打开路径: " + text);
                  invoke('open_local_file', { path: text }).catch(err => {
                    console.error("Failed native open:", err);
                    alert("无法打开文件: " + err);
                  });
                }}
                title={`点击打开文件: ${text}`}
              >
                {children}
              </span>
            );
          }

          return !inline && match ? (
            <SyntaxHighlighter
              style={vscDarkPlus as any}
              language={match[1]}
              PreTag="div"
              className="rounded-xl !bg-[#0d0d0d] !my-4 border border-white/5"
              {...props}
            >
              {text}
            </SyntaxHighlighter>
          ) : (
            <code className="bg-white/10 px-1.5 py-0.5 rounded text-blue-300 font-mono text-[0.9em]" {...props}>
              {children}
            </code>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
    </div>
  );
};
