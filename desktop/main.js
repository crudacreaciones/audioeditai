// Electron shell: starts the local Python backend and shows the UI in a native window.
const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

// The port must stay fixed: it is part of the Spotify Redirect URI registered by the user.
const PORT = Number(process.env.SWC_PORT || 8765);
const BASE = `http://127.0.0.1:${PORT}`;
let backend = null;
let win = null;

function projectRoot() {
  // packaged: resources/ (extraResources); dev: repository root
  const packaged = path.join(process.resourcesPath || '', 'run.py');
  return fs.existsSync(packaged) ? process.resourcesPath : path.resolve(__dirname, '..');
}

function pythonCandidates() {
  if (process.env.SWC_PYTHON) return [process.env.SWC_PYTHON];
  return process.platform === 'win32' ? ['python', 'py'] : ['python3', 'python'];
}

function health() {
  return new Promise((resolve) => {
    const req = http.get(`${BASE}/api/health`, { timeout: 1000 }, (res) => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function startBackend() {
  if (await health()) return; // already running (e.g. started manually)
  const root = projectRoot();
  let lastError = '';
  for (const py of pythonCandidates()) {
    try {
      backend = spawn(py, [path.join(root, 'run.py'), '--port', String(PORT)], {
        cwd: root, env: { ...process.env, PYTHONUNBUFFERED: '1' }, windowsHide: true,
      });
    } catch (e) { lastError = String(e); continue; }
    let failed = false;
    backend.on('error', (e) => { failed = true; lastError = String(e); });
    backend.stderr.on('data', (d) => { lastError = String(d).slice(-2000); process.stderr.write(d); });
    backend.stdout.on('data', (d) => process.stdout.write(d));
    for (let i = 0; i < 100 && !failed && backend.exitCode === null; i++) {
      if (await health()) return;
      await new Promise((r) => setTimeout(r, 200));
    }
    if (backend.exitCode === null) backend.kill();
  }
  throw new Error(`No se pudo iniciar el servidor local (Python).\n\n${lastError}\n\n` +
    'Comprueba que Python 3.10+ está instalado y ejecuta: pip install -r backend/requirements.txt');
}

function createWindow() {
  win = new BrowserWindow({
    width: 1360, height: 860, minWidth: 1024, minHeight: 640,
    backgroundColor: '#0b0d12', title: 'Spotify to WAV Converter', autoHideMenuBar: true, show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  // Spotify login and external links open in the system browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url) && !url.startsWith(BASE)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith(BASE)) { e.preventDefault(); shell.openExternal(url); } });
  win.once('ready-to-show', () => win.show());
  win.loadURL(BASE + '/');
}

ipcMain.handle('swc:pick-folder', async (_e, title) => {
  const r = await dialog.showOpenDialog(win, { title: title || 'Seleccionar carpeta', properties: ['openDirectory', 'createDirectory'] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle('swc:pick-files', async (_e, title) => {
  const r = await dialog.showOpenDialog(win, {
    title: title || 'Seleccionar archivos de audio',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Audio', extensions: ['mp3', 'flac', 'm4a', 'aac', 'ogg', 'oga', 'wav'] }],
  });
  return r.canceled ? null : r.filePaths;
});
ipcMain.handle('swc:open-external', (_e, url) => {
  if (/^https:\/\//.test(url) || url.startsWith(BASE)) return shell.openExternal(url);
  return null;
});

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    try {
      await startBackend();
      createWindow();
    } catch (e) {
      dialog.showErrorBox('Spotify to WAV Converter', e.message);
      app.quit();
    }
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', () => { if (backend && backend.exitCode === null) backend.kill(); });
}
