import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Markdown } from './Markdown';
import { useI18n } from '../hooks/useI18n';

vi.mock('../hooks/useI18n', () => ({
  useI18n: vi.fn(),
}));

const mockedUseI18n = vi.mocked(useI18n);
const clipboardWriteText = vi.fn();

describe('Markdown', () => {
  beforeEach(() => {
    clipboardWriteText.mockReset();

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: clipboardWriteText.mockResolvedValue(undefined),
      },
    });

    mockedUseI18n.mockReturnValue({
      locale: 'en',
      changeLanguage: vi.fn(),
      t: (key: string) =>
        (
          {
            'common.copy': 'Copy',
            'common.copied': 'Copied',
          } as Record<string, string>
        )[key] ?? key,
    });
  });

  it('copies fenced code blocks from the top-right action', async () => {
    render(
      <Markdown
        content={[
          '```markdown',
          '# Optimized Prompt',
          '- hard signal 1',
          '- hard signal 2',
          '```',
        ].join('\n')}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenCalledWith('# Optimized Prompt\n- hard signal 1\n- hard signal 2');
    });

    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('updates the copy button label when parent translations change', () => {
    mockedUseI18n
      .mockReturnValueOnce({
        locale: 'en',
        changeLanguage: vi.fn(),
        t: (key: string) =>
          (
            {
              'common.copy': 'Copy',
              'common.copied': 'Copied',
            } as Record<string, string>
          )[key] ?? key,
      })
      .mockReturnValueOnce({
        locale: 'zh',
        changeLanguage: vi.fn(),
        t: (key: string) =>
          (
            {
              'common.copy': '复制',
              'common.copied': '已复制',
            } as Record<string, string>
          )[key] ?? key,
      });

    const content = ['```markdown', '# Prompt', '```'].join('\n');
    const { rerender } = render(<Markdown content={content} />);

    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();

    rerender(<Markdown content={content} />);

    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();
  });

  it('allows long links to wrap inside chat bubbles', () => {
    const longUrl =
      'https://apps.apple.com/cn/app/%E9%9A%8F%E5%8F%A3%E8%AE%B0-ai%E8%AF%AD%E9%9F%B3%E5%BE%85%E5%8A%9E%E6%B8%85%E5%8D%95%E4%BB%8E%E6%8F%90%E9%86%92%E4%BA%8B%E9%A1%B9%E5%88%B0%E6%97%A5%E7%A8%8B';

    const { container } = render(<Markdown content={`帮我研究下${longUrl}在中国区的asa投放策略`} />);

    expect(container.firstElementChild).toHaveClass('[overflow-wrap:anywhere]');
    expect(screen.getByRole('link')).toHaveClass('break-words', '[overflow-wrap:anywhere]');
  });
});
