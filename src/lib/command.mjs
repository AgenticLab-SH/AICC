import { spawn } from 'node:child_process';

export function runCommand(executable, args = [], options = {}) {
  const timeoutMs = options.timeoutMs ?? 8_000;
  const maxBytes = options.maxBytes ?? 1_000_000;

  return new Promise(resolve => {
    const startedAt = Date.now();
    let stdout = '';
    let stderr = '';
    let settled = false;
    let timedOut = false;
    let overflow = false;
    let child;

    const finish = result => {
      if (settled) return;
      settled = true;
      resolve({
        ok: false,
        executable,
        args,
        stdout,
        stderr,
        exitCode: null,
        signal: null,
        timedOut,
        overflow,
        durationMs: Date.now() - startedAt,
        ...result
      });
    };

    try {
      child = spawn(executable, args, {
        cwd: options.cwd,
        env: options.env ?? process.env,
        shell: false,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe']
      });
    } catch (error) {
      finish({ error: error.message });
      return;
    }

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
      setTimeout(() => child.kill('SIGKILL'), 500).unref();
    }, timeoutMs);
    timer.unref();

    const append = (current, chunk) => {
      if (overflow) return current;
      const next = current + chunk.toString('utf8');
      if (Buffer.byteLength(next, 'utf8') > maxBytes) {
        overflow = true;
        child.kill('SIGTERM');
        return next.slice(0, maxBytes);
      }
      return next;
    };

    child.stdout.on('data', chunk => { stdout = append(stdout, chunk); });
    child.stderr.on('data', chunk => { stderr = append(stderr, chunk); });
    child.on('error', error => {
      clearTimeout(timer);
      finish({ error: error.message });
    });
    child.on('close', (exitCode, signal) => {
      clearTimeout(timer);
      finish({
        ok: exitCode === 0 && !timedOut && !overflow,
        exitCode,
        signal,
        error: timedOut ? 'command timed out' : overflow ? 'command output exceeded limit' : null
      });
    });
  });
}

export function envCommand(prefix, fallback) {
  const executable = process.env[`${prefix}_EXECUTABLE`]?.trim() || fallback.executable;
  const rawArgs = process.env[`${prefix}_ARGS_JSON`]?.trim();
  if (!rawArgs) return { executable, args: fallback.args };
  try {
    const args = JSON.parse(rawArgs);
    return { executable, args: Array.isArray(args) ? args.map(String) : fallback.args };
  } catch {
    return { executable, args: fallback.args };
  }
}
