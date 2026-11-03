import { StyleSheet, Text, View } from 'react-native';

import { colors } from '../theme';

const BARS = [0.35, 0.7, 1, 0.55, 0.85, 0.45];

export function Logo({ size = 56 }: { size?: number }) {
  const barW = size / 11;
  return (
    <View style={styles.row} accessibilityRole="header" accessibilityLabel="WAVIFY">
      <View style={[styles.mark, { width: size, height: size, borderRadius: size * 0.28 }]}>
        {BARS.map((h, i) => (
          <View key={i} style={{ width: barW, height: size * 0.62 * h, borderRadius: barW, backgroundColor: '#04140A',
            marginHorizontal: barW * 0.32 }} />
        ))}
      </View>
      <Text style={[styles.name, { fontSize: size * 0.62 }]}>WAVIFY</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  mark: { backgroundColor: colors.accent, flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  name: { color: colors.text, fontWeight: '800', letterSpacing: 2 },
});
