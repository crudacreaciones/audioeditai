import { checkSpotifyLink, extractLink } from '../src/lib/spotifyLink';
import { isSecureEnough } from '../src/lib/config';

const ID = '4uLU6hMCjMI75M1A2tKUQC';

test.each([
  `https://open.spotify.com/track/${ID}?si=abc`, `open.spotify.com/intl-es/track/${ID}`, `spotify:track:${ID}`,
  'https://spotify.link/AbCdEf123',
])('accepts %s', (l) => expect(checkSpotifyLink(l)).toEqual({ ok: true }));

test.each([
  ['', 'Pega un enlace'], ['hola', 'no parece'], [`https://open.spotify.com/album/${ID}`, 'canción'],
  [`https://open.spotify.com/playlist/${ID}`, 'canción'], ['https://youtube.com/watch?v=1', 'no parece'],
])('rejects %s', (l, msg) => {
  const r = checkSpotifyLink(l);
  expect(r.ok).toBe(false);
  if (!r.ok) expect(r.message).toContain(msg);
});

test('extracts the link from shared text', () => {
  expect(extractLink(`Escucha «Luz» en Spotify: https://open.spotify.com/track/${ID}?si=x`))
    .toBe(`https://open.spotify.com/track/${ID}?si=x`);
});

test('https required except for local development hosts', () => {
  expect(isSecureEnough('https://api.wavify.app')).toBe(true);
  expect(isSecureEnough('http://192.168.1.20:8000')).toBe(true);
  expect(isSecureEnough('http://localhost:8000')).toBe(true);
  expect(isSecureEnough('http://api.wavify.app')).toBe(false);
});
