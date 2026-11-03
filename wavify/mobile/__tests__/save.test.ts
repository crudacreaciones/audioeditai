import { Platform } from 'react-native';

jest.mock('expo-file-system', () => {
  const downloaded = { exists: true, size: 1000, uri: 'file:///cache/a.mp3', delete: jest.fn(),
    bytes: jest.fn(async () => new Uint8Array([1, 2])) };
  const target = { write: jest.fn(async () => undefined) };
  const dir = { uri: 'content://tree/Music', createFile: jest.fn(() => target) };
  const File = Object.assign(jest.fn().mockImplementation(() => ({ exists: false, delete: jest.fn() })),
    { downloadFileAsync: jest.fn(async () => downloaded) });
  return { File, Directory: { pickDirectoryAsync: jest.fn(async () => dir) }, Paths: { cache: 'cache' },
    __test: { downloaded, target, dir } };
});
jest.mock('expo-sharing', () => ({ isAvailableAsync: jest.fn(async () => true), shareAsync: jest.fn(async () => undefined) }));

import * as Sharing from 'expo-sharing';
import { saveMp3 } from '../src/lib/save';

const fs = jest.requireMock('expo-file-system');
const { downloaded, target, dir } = fs.__test;

function setOS(os: string) {
  Object.defineProperty(Platform, 'OS', { get: () => os, configurable: true });
}

beforeEach(() => jest.clearAllMocks());

test('android: writes the MP3 into the folder the user picks', async () => {
  setOS('android');
  const r = await saveMp3('https://api/x.mp3', 'A - B.mp3');
  expect(fs.File.downloadFileAsync).toHaveBeenCalledWith('https://api/x.mp3', expect.anything(), { idempotent: true });
  expect(dir.createFile).toHaveBeenCalledWith('A - B.mp3', 'audio/mpeg');
  expect(target.write).toHaveBeenCalledWith(new Uint8Array([1, 2]));
  expect(downloaded.delete).toHaveBeenCalled();
  expect(r).toEqual({ saved: true, location: 'content://tree/Music' });
  expect(Sharing.shareAsync).not.toHaveBeenCalled();
});

test('android: picker dismissed -> share sheet fallback', async () => {
  setOS('android');
  fs.Directory.pickDirectoryAsync.mockRejectedValueOnce(new Error('cancelled'));
  await saveMp3('u', 'a.mp3');
  expect(Sharing.shareAsync).toHaveBeenCalledWith('file:///cache/a.mp3', expect.objectContaining({ mimeType: 'audio/mpeg' }));
});

test('ios: opens the share sheet (Guardar en Archivos)', async () => {
  setOS('ios');
  await saveMp3('u', 'a.mp3');
  expect(fs.Directory.pickDirectoryAsync).not.toHaveBeenCalled();
  expect(Sharing.shareAsync).toHaveBeenCalledWith('file:///cache/a.mp3', { mimeType: 'audio/mpeg', UTI: 'public.mp3', dialogTitle: 'Guardar MP3' });
});

test('empty download is reported, nothing is shared', async () => {
  setOS('ios');
  fs.File.downloadFileAsync.mockResolvedValueOnce({ ...downloaded, size: 0 });
  await expect(saveMp3('u', 'a.mp3')).rejects.toThrow('ha fallado');
  expect(Sharing.shareAsync).not.toHaveBeenCalled();
});
