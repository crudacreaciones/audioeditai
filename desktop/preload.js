// Minimal, explicit bridge between the UI and native desktop features.
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('swcDesktop', {
  pickFolder: (title) => ipcRenderer.invoke('swc:pick-folder', title),
  pickFiles: (title) => ipcRenderer.invoke('swc:pick-files', title),
  openExternal: (url) => ipcRenderer.invoke('swc:open-external', url),
  getPathForFile: (file) => { try { return webUtils.getPathForFile(file); } catch { return null; } },
});
