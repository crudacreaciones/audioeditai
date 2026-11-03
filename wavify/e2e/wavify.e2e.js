// End-to-end test of the WAVIFY app (Expo web build) against the WAVIFY backend.
//   node e2e/wavify.e2e.js http://127.0.0.1:8011 <screenshots-dir>
const { chromium, devices } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const [APP, SHOTS] = process.argv.slice(2);
fs.mkdirSync(SHOTS, { recursive: true });
const T = (id) => `[data-testid="${id}"]`;
const ok = (m) => console.log(`✓ ${m}`);
const assert = (c, m) => { if (!c) throw new Error(`ASSERT: ${m}`); };
const link = (id) => `https://open.spotify.com/track/${id}?si=e2e`;

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices['iPhone 13'], acceptDownloads: true, colorScheme: 'dark' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const shot = (n) => page.screenshot({ path: path.join(SHOTS, `${n}.png`), fullPage: true });
  const search = async (url) => {
    await page.fill(T('link-input'), url);
    await page.click(T('go'));
  };
  const newSearch = async () => { await page.click(T('new')); await page.waitForSelector(T('go')); };
  try {
    await page.goto(APP);
    await page.waitForSelector('text=Tu música, lista para llevar');
    await shot('01-inicial');
    ok('initial screen');

    await search('https://open.spotify.com/album/4uLU6hMCjMI75M1A2tKUQC');
    await page.waitForSelector(`${T('error')} >> text=Pega el enlace de una canción`);
    ok('album link rejected');

    // full flow -> MP3 saved
    await page.click(T('quality-320'));
    await search(link('4uLU6hMCjMI75M1A2tKUQC'));
    await page.waitForSelector(T('current-step'));
    await shot('02-buscando');
    await page.waitForSelector(T('availability'), { timeout: 60000 });
    await page.waitForSelector(`${T('quality')} >> text=MP3 · 320 kbps`);
    await shot('03-archivo-listo');
    const [dl] = await Promise.all([page.waitForEvent('download'), page.click(T('save'))]);
    assert(dl.suggestedFilename() === 'Aurora Libre - Luz de Mañana.mp3', dl.suggestedFilename());
    const saved = path.join(SHOTS, 'saved.mp3');
    await dl.saveAs(saved);
    const probe = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name,bit_rate:format_tags=title,artist',
      '-of', 'default=nw=1', saved]).toString();
    assert(/codec_name=mp3/.test(probe) && /bit_rate=320000/.test(probe) && /TAG:title=Luz de Mañana/.test(probe), probe);
    await page.waitForSelector(`${T('saved')}`);
    ok(`link → identified → matched → downloaded → MP3 320 kbps saved (${fs.statSync(saved).size} bytes, verified with ffprobe)`);

    // stream-only source
    await newSearch();
    await search(link('0000000000000000000002'));
    await page.waitForSelector(T('no-results'), { timeout: 30000 });
    assert((await page.textContent(T('no-results'))).includes('solo reproducción'), 'stream only message');
    await shot('04-sin-version-autorizada');
    ok('stream-only result is not downloaded');

    // only a cover by another artist exists
    await newSearch();
    await search(link('0000000000000000000003'));
    await page.waitForSelector(T('no-results'), { timeout: 30000 });
    assert((await page.textContent(T('no-results'))).includes('ninguno es con seguridad la misma grabación'), 'unverified');
    ok('cover by another artist is not accepted');

    // long conversion: live progress, then cancel
    await newSearch();
    await search(link('0000000000000000000009'));
    await page.waitForSelector(`${T('current-step')} >> text=Convirtiendo`, { timeout: 60000 });
    await shot('05-convirtiendo');
    await page.click(T('cancel'));
    await page.waitForSelector(T('progress'), { state: 'detached' });
    ok('long conversion shows progress and can be cancelled');

    if (errors.length) throw new Error(errors.join('\n'));
    console.log('\nWAVIFY E2E OK');
  } catch (e) {
    await shot('zz-failure').catch(() => {});
    console.error(e);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
