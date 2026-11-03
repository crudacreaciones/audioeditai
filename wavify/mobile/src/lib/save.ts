import { Directory, File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { Platform } from 'react-native';

export type SaveResult = { saved: boolean; location?: string };

/**
 * Save the MP3 on the device.
 *  - Android: the user picks a folder (Storage Access Framework) and the file is written there.
 *  - iOS: the system share sheet opens ("Guardar en Archivos", AirDrop…).
 *  - Web: regular browser download.
 * Everything used here ships in Expo Go.
 */
export async function saveMp3(url: string, fileName: string): Promise<SaveResult> {
  if (Platform.OS === 'web') {
    const res = await fetch(url);
    if (!res.ok) throw new Error('El archivo ya no está disponible. Vuelve a convertir la canción.');
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 10000);
    return { saved: true, location: 'Descargas' };
  }

  const cached = new File(Paths.cache, fileName);
  if (cached.exists) cached.delete();
  const local = await File.downloadFileAsync(url, cached, { idempotent: true });
  if (!local.exists || local.size === 0) throw new Error('La descarga del archivo ha fallado.');

  if (Platform.OS === 'android') {
    try {
      const dir = await Directory.pickDirectoryAsync();
      const target = dir.createFile(fileName, 'audio/mpeg');
      await target.write(await local.bytes());
      local.delete();
      return { saved: true, location: dir.uri };
    } catch {
      // picker dismissed or not available: fall back to the share sheet
    }
  }
  if (!(await Sharing.isAvailableAsync())) throw new Error('Este dispositivo no permite compartir archivos.');
  await Sharing.shareAsync(local.uri, { mimeType: 'audio/mpeg', UTI: 'public.mp3', dialogTitle: 'Guardar MP3' });
  return { saved: true };
}
