import { Image, StyleSheet, Text, View } from 'react-native';

import type { Track } from '../api/types';
import { colors, radius } from '../theme';

export function fmtDuration(sec: number): string {
  const s = Math.round(sec || 0);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function TrackCard({ track, children }: { track: Track; children?: React.ReactNode }) {
  return (
    <View style={styles.card} testID="track-card">
      <View style={styles.row}>
        {track.cover_url ? <Image source={{ uri: track.cover_url }} style={styles.cover} accessibilityIgnoresInvertColors />
          : <View style={[styles.cover, styles.placeholder]} />}
        <View style={styles.meta}>
          <Text style={styles.title} numberOfLines={2}>{track.title}</Text>
          <Text style={styles.artist} numberOfLines={1}>{track.artists.join(', ')}</Text>
          <Text style={styles.album} numberOfLines={1}>{track.album} · {fmtDuration(track.duration)}</Text>
        </View>
      </View>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.m, padding: 16, gap: 14, borderWidth: 1, borderColor: colors.border },
  row: { flexDirection: 'row', gap: 14, alignItems: 'center' },
  cover: { width: 76, height: 76, borderRadius: 10, backgroundColor: colors.surface2 },
  placeholder: { borderWidth: 1, borderColor: colors.border },
  meta: { flex: 1, gap: 3 },
  title: { color: colors.text, fontSize: 18, fontWeight: '700' },
  artist: { color: colors.text2, fontSize: 15 },
  album: { color: colors.text3, fontSize: 13 },
});
