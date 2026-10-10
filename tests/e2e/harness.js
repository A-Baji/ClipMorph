// Shared node entry point for the #259 CI smoke test.
//
// Spawns the Python harness (tests/e2e/harness.py --serve) so the node smoke
// test and the Python-driven audit/re-audit all boot the identical seeded
// workspace and server. This module has no Playwright dependency of its own;
// the smoke test (tests/e2e/smoke.js) drives the returned URL with Playwright.
'use strict';

const { spawn } = require('node:child_process');
const readline = require('node:readline');
const path = require('node:path');

// `python` is on PATH in CI; locally point CLIPMORPH_PYTHON at the workspace
// interpreter (the conda env here is not on PATH).
const PYTHON = process.env.CLIPMORPH_PYTHON || process.env.PYTHON || 'python';
const HARNESS = path.join(__dirname, 'harness.py');

/**
 * Boot the local ClipMorph service against a seeded fixture workspace.
 * @param {{scenario?: string, python?: string, timeoutMs?: number}} [options]
 * @returns {Promise<{url: string, port: number, dataDir: string,
 *   viewports: Record<string, {width: number, height: number}>,
 *   stop: () => void}>}
 */
function startServer(options = {}) {
  const scenario = options.scenario || 'states';
  const python = options.python || PYTHON;
  const timeoutMs = options.timeoutMs || 60000;

  return new Promise((resolve, reject) => {
    const child = spawn(
      python,
      ['-u', HARNESS, '--serve', '--scenario', scenario],
      { stdio: ['ignore', 'pipe', 'pipe'] },
    );
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill();
      reject(new Error(`harness did not report a URL within ${timeoutMs}ms`));
    }, timeoutMs);

    readline.createInterface({ input: child.stdout }).on('line', (line) => {
      if (settled) return;
      let payload;
      try {
        payload = JSON.parse(line);
      } catch {
        return; // skip non-JSON banner lines
      }
      settled = true;
      clearTimeout(timer);
      resolve({
        url: payload.url,
        port: payload.port,
        dataDir: payload.data_dir,
        viewports: payload.viewports,
        stop: () => child.kill(),
      });
    });
    child.stderr.on('data', (chunk) => process.stderr.write(chunk));
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
    child.on('exit', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new Error(`harness exited with code ${code} before reporting a URL`));
    });
  });
}

module.exports = { startServer, PYTHON, HARNESS };
