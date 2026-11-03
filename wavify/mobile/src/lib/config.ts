import Constants from 'expo-constants';
import { Platform } from 'react-native';

const PRIVATE_HOST = /^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)$/;

/** Base URL of the WAVIFY backend. Holds no secrets: credentials live only on the server. */
export function apiBaseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv.replace(/\/+$/, '');
  // Development: reuse the dev machine's address that Expo Go is already talking to.
  const hostUri = Constants.expoConfig?.hostUri;
  if (hostUri) return `http://${hostUri.split(':')[0]}:8000`;
  return Platform.OS === 'web' ? 'http://127.0.0.1:8000' : 'http://localhost:8000';
}

/** HTTPS is required except for local development hosts. */
export function isSecureEnough(url: string): boolean {
  const m = /^(https?):\/\/([^/:]+)/i.exec(url);
  if (!m) return false;
  return m[1].toLowerCase() === 'https' || PRIVATE_HOST.test(m[2]);
}
