// Smoke test of the Electron shell: it must start the Python backend, open the UI and expose the native bridge.
//   xvfb-run node e2e/desktop.e2e.js <screenshot.png>
const { _electron: electron } = require('playwright');
const http = require('http');
const path = require('path');

const desktopDir = path.resolve(__dirname, '..', 'desktop');
const PORT = process.env.SWC_PORT || '8798';
const health = () => new Promise((r) => http.get(`http://127.0.0.1:${PORT}/api/health`, (res) => { res.resume(); r(res.statusCode === 200); }).on('error', () => r(false)));

(async () => {
  const args = [desktopDir];
  if (process.getuid && process.getuid() === 0) args.push('--no-sandbox');
  const app = await electron.launch({
    executablePath: require(path.join(desktopDir, 'node_modules', 'electron')),
    args, env: { ...process.env, SWC_PORT: PORT },
  });
  try {
    const win = await app.firstWindow();
    await win.waitForSelector('#nav a[data-route="dashboard"]', { timeout: 30000 });
    await win.waitForSelector('.page[data-page="dashboard"] .stat');
    const bridge = await win.evaluate(() => Object.keys(window.swcDesktop || {}).sort().join(','));
    if (bridge !== 'getPathForFile,openExternal,pickFiles,pickFolder') throw new Error(`bridge: ${bridge}`);
    await win.click('#nav a[data-route="import"]');
    await win.waitForSelector('button:has-text("Carpeta…")');
    if (process.argv[2]) await win.screenshot({ path: process.argv[2] });
    console.log(`✓ Electron window loaded backend on :${PORT}, desktop bridge = ${bridge}`);
  } finally {
    await app.close();
  }
  await new Promise((r) => setTimeout(r, 1500));
  if (await health()) { console.error('backend still running after quit'); process.exit(1); }
  console.log('✓ backend stopped on quit\nDESKTOP OK');
})().catch((e) => { console.error(e); process.exit(1); });
