import { describe, expect, it } from 'vitest';

import { mergeToolActivity, type ToolActivityPayload } from './useBackendConnection';

describe('mergeToolActivity', () => {
  it('preserves output when replacing a start event with a terminal event', () => {
    const start: ToolActivityPayload = {
      run_id: 'run-1',
      tool_name: 'run_skill_script',
      phase: 'start',
      input: { command: 'python report.py' },
    };

    const merged = mergeToolActivity([start], {
      run_id: 'run-1',
      tool_name: 'run_skill_script',
      phase: 'error',
      duration_ms: 8,
      output: 'Script not found: report.py',
    });

    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      phase: 'error',
      duration_ms: 8,
      output: 'Script not found: report.py',
      input: { command: 'python report.py' },
    });
  });
});
