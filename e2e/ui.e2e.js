// End-to-end UI test: drives every section of the app in Chromium against a running server
// started with backend/tests/demo_server.py (sample audio + offline fake Spotify).
//
//   node e2e/ui.e2e.js http://127.0.0.1:8799 <media-dir> <screenshot-dir> <export-dir>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [BASE, MEDIA, SHOTS, EXPORT] = process.argv.slice(2);
if (!BASE || !MEDIA || !SHOTS || !EXPORT) { console.error('usage: node ui.e2e.js BASE MEDIA SHOTS EXPORT'); process.exit(2); }
fs.mkdirSync(SHOTS, { recursive: true });

const step = (m) => console.log(`✓ ${m}`);
function assert(c, m) { if (!c) throw new Error(`ASSERT: ${m}`); }

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon/.test(m.text())) errors.push(`console: ${m.text()}`); });
  const shot = (n) => page.screenshot({ path: path.join(SHOTS, `${n}.png`) });
  const nav = async (route) => { await page.click(`#nav a[data-route="${route}"]`); await page.waitForSelector(`.page[data-page="${route}"]`); };

  try {
    // 1. Dashboard (empty)
    await page.goto(BASE);
    await page.waitForSelector('.page[data-page="dashboard"] .stat');
    await page.waitForSelector('#foot-ffmpeg .dot.on');
    await shot('01-dashboard-empty');
    step('dashboard renders, FFmpeg detected');

    // 2. Settings: Spotify client id
    await nav('settings');
    await page.fill('#set-client-id', 'test-client-id');
    await page.click('#set-save');
    await page.waitForSelector('.toast:has-text("Configuración guardada")');
    await shot('02-settings');
    step('settings saved');

    // 3. Import via folder browser + manual path
    await nav('import');
    await page.click('#imp-browse');
    await page.waitForSelector('.modal .browser-list .browser-row');
    await page.fill('.modal .browser-path input', MEDIA);
    await page.click('.modal .browser-path button');
    await page.waitForSelector('.modal .browser-row:has-text("album")');
    await page.click('.modal button:has-text("Esta carpeta")');
    await page.waitForSelector(`.list-item:has-text("${path.basename(MEDIA)}")`);
    await page.click('#imp-start');
    await page.waitForSelector('[data-job] b:has-text("Completada")', { timeout: 60000 });
    const jobText = await page.textContent('[data-job]');
    assert(jobText.includes('7 importados') && jobText.includes('1 duplicados') && jobText.includes('1 errores'), `import summary: ${jobText}`);
    await page.click('[data-job] summary');
    await shot('03-import');
    step('folder import: 7 imported, 1 duplicate, 1 corrupt rejected');

    // 4. Library: search, facets, edit, preview, duplicates
    await nav('library');
    await page.waitForSelector('#lib-table tbody tr');
    assert((await page.$$('#lib-table tbody tr')).length === 7, 'library has 7 rows');
    await page.fill('#lib-search', 'armónico');
    await page.waitForFunction(() => document.querySelectorAll('#lib-table tbody tr').length === 1);
    await page.fill('#lib-search', '');
    await page.waitForFunction(() => document.querySelectorAll('#lib-table tbody tr').length === 7);
    await page.click('.facet:has-text("Codec Lab")');
    await page.waitForFunction(() => document.querySelectorAll('#lib-table tbody tr').length === 3);
    await page.click('.badge.blue:has-text("Artista")');
    await page.waitForFunction(() => document.querySelectorAll('#lib-table tbody tr').length === 7);
    // edit metadata of the raw AAC (title guessed from file name)
    await page.click('#lib-table tr:has-text("Crudo") button[title="Editar metadatos"]');
    await page.waitForSelector('.modal input[name="title"]');
    await page.fill('.modal input[name="genre"]', 'Experimental');
    await page.fill('.modal input[name="year"]', '2025');
    await shot('04-library-edit');
    await page.click('.modal button:has-text("Guardar")');
    await page.waitForSelector('#lib-table tr:has-text("Experimental")');
    // preview
    await page.click('#lib-table tr:has-text("Segundo Armónico") button[title="Vista previa"]');
    await page.waitForSelector('#player.show audio');
    await page.waitForFunction(() => { const a = document.querySelector('#player audio'); return a && a.currentTime > 0.2; }, null, { timeout: 15000 });
    await shot('05-library');
    await page.click('#player button[title="Cerrar reproductor"]');
    await page.click('button:has-text("Duplicados")');
    await page.waitForSelector('.modal:has-text("Idénticos")').catch(() => page.waitForSelector('.modal:has-text("No hay duplicados")'));
    await page.keyboard.press('Escape');
    step('library: search, facet filter, metadata edit, audio preview playing, duplicates');

    // 5. Spotify: OAuth popup, search, playlists, work list, matching
    await nav('spotify');
    const [popup] = await Promise.all([page.waitForEvent('popup'), page.click('#connect-spotify')]);
    await popup.waitForEvent('close', { timeout: 20000 }).catch(() => {});
    await page.waitForSelector('.badge.green:has-text("Usuario Demo")', { timeout: 20000 });
    step('Spotify OAuth (PKCE) popup flow connected');
    await page.fill('#sp-search', 'onda');
    await page.click('#sp-search-btn');
    await page.waitForSelector('tr:has-text("La Primera Onda")');
    await shot('06-spotify-search');
    await page.click('tr:has-text("La Primera Onda") button:has-text("Añadir")');
    await page.waitForSelector('tr:has-text("La Primera Onda") button:has-text("Añadida")');
    await page.fill('#sp-search', 'tonos');
    await page.click('.seg button:has-text("Álbumes")');
    await page.waitForSelector('.tile:has-text("Tonos de Prueba")');
    await page.click('.tile:has-text("Tonos de Prueba")');
    await page.waitForSelector('tr:has-text("Segundo Armónico")');
    await page.click('button:has-text("Añadir todas")');
    await page.waitForSelector('.toast:has-text("añadida")');
    await page.click('.seg button:has-text("Mis playlists")');
    await page.waitForSelector('.tile:has-text("Para convertir")');
    await shot('07-spotify-playlists');
    await page.click('.tile:has-text("Para convertir")');
    await page.waitForSelector('tr:has-text("Canción Sin Archivo")');
    await page.click('button:has-text("Añadir todas")');
    await page.waitForSelector('tr:has-text("Canción Sin Archivo") button:has-text("Añadida")');
    await page.click('.seg button:has-text("Lista de trabajo")');
    await page.waitForSelector('#worklist tbody tr');
    assert((await page.$$('#worklist tbody tr')).length === 4, 'work list has 4 tracks');
    await page.click('button:has-text("Asociar con archivos locales")');
    await page.waitForSelector('.toast:has-text("3 coincidencias")');
    await page.waitForFunction(() => document.querySelectorAll('#worklist .badge.green').length === 3);
    await shot('08-spotify-worklist');
    step('search/albums/playlists → work list → auto-matched 3 local files');
    await page.click('button:has-text("Convertir disponibles (3)")');
    await page.waitForSelector('.page[data-page="convert"]');

    // 6. Conversion: batch 48 kHz / 24-bit stereo
    await page.waitForSelector('#conv-start:has-text("Convertir 3 pistas")');
    await page.click('.seg button:has-text("48 kHz")');
    await page.click('.seg button:has-text("24 bits")');
    await shot('09-convert-setup');
    await page.click('#conv-start');
    await page.waitForFunction(() => {
      const rows = [...document.querySelectorAll('#jobs-table tbody tr')];
      return rows.length === 3 && rows.every((r) => r.dataset.status === 'done');
    }, null, { timeout: 120000 });
    assert((await page.$$('#jobs-table .badge.green:has-text("Verificado")')).length === 3, '3 verified');
    step('batch conversion of 3 tracks to 48 kHz/24-bit, all verified');
    await page.click('#jobs-table tbody tr >> nth=0 >> button[title="Verificación"]');
    await page.waitForSelector('.modal:has-text("decodificación completa")');
    await shot('10-verify-report');
    await page.click('.modal button:has-text("Cerrar")');

    // long file at 192 kHz / 32-bit float, then cancel mid-way
    await nav('library');
    await page.click('#lib-table tr:has-text("Largo") input[type=checkbox]');
    await page.click('#lib-convert');
    await page.waitForSelector('#conv-start');
    await page.click('.seg button:has-text("192 kHz")');
    await page.click('.seg button:has-text("32 bits float")');
    await page.click('#conv-start');
    await page.waitForSelector('#jobs-table tr[data-status="running"] .progress', { timeout: 20000 });
    await page.waitForFunction(() => { const s = document.querySelector('#jobs-table tr[data-status="running"] .num'); return s && parseInt(s.textContent) >= 1; }, null, { timeout: 30000 });
    await shot('11-convert-progress');
    await page.click('#jobs-table tr[data-status="running"] button:has-text("Cancelar")');
    await page.waitForSelector('#jobs-table tr[data-status="cancelled"]', { timeout: 20000 });
    step('192 kHz/32f conversion shows live progress and is cancelled');

    // export the 3 verified WAVs through the folder picker
    await page.click('#jobs-table thead input[type=checkbox]');
    await page.waitForSelector('#conv-export:has-text("Exportar (3)")');
    await page.click('#conv-export');
    await page.waitForSelector('.modal .browser-path input');
    await page.fill('.modal .browser-path input', EXPORT);
    await page.click('.modal button:has-text("Seleccionar esta carpeta")');
    await page.waitForSelector('.toast:has-text("3 archivo(s) exportado(s)")');
    const exported = fs.readdirSync(EXPORT).filter((f) => f.endsWith('.wav'));
    assert(exported.length === 3, `exported files: ${exported}`);
    await shot('12-convert-done');
    step(`exported 3 WAV files: ${exported.join(', ')}`);

    // 7. History
    await nav('history');
    await page.waitForSelector('table tbody tr');
    await shot('13-history');
    await page.click('.seg button:has-text("Registro de operaciones")');
    await page.waitForSelector('table tbody tr:has-text("spotify")');
    await shot('14-logs');
    step('history & operation logs');

    // 8. Dashboard (populated)
    await nav('dashboard');
    await page.waitForSelector('.list-item');
    await shot('15-dashboard');
    step('dashboard populated');

    if (errors.length) throw new Error('browser errors:\n' + errors.join('\n'));
    console.log('\nE2E OK');
  } catch (e) {
    await shot('zz-failure').catch(() => {});
    console.error(e);
    if (errors.length) console.error(errors.join('\n'));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
