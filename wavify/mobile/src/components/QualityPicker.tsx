import { Pressable, StyleSheet, Text, View } from 'react-native';

import { BITRATES, type Bitrate } from '../api/types';
import { colors, radius } from '../theme';

export function QualityPicker({ value, onChange, disabled }: { value: Bitrate; onChange: (b: Bitrate) => void; disabled?: boolean }) {
  return (
    <View>
      <Text style={styles.label}>Calidad MP3</Text>
      <View style={styles.seg} accessibilityRole="radiogroup">
        {BITRATES.map((b) => (
          <Pressable key={b} onPress={() => onChange(b)} disabled={disabled} testID={`quality-${b}`}
            accessibilityRole="radio" accessibilityState={{ checked: b === value, disabled }}
            style={[styles.opt, b === value && styles.optOn]}>
            <Text style={[styles.txt, b === value && styles.txtOn]}>{b}</Text>
          </Pressable>
        ))}
      </View>
      <Text style={styles.hint}>kbps · Nunca se supera la calidad del archivo original.</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  label: { color: colors.text2, fontSize: 13, fontWeight: '600', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 },
  seg: { flexDirection: 'row', backgroundColor: colors.surface, borderRadius: radius.pill, padding: 4, borderWidth: 1, borderColor: colors.border },
  opt: { flex: 1, paddingVertical: 10, borderRadius: radius.pill, alignItems: 'center' },
  optOn: { backgroundColor: colors.surface2, borderWidth: 1, borderColor: colors.border },
  txt: { color: colors.text3, fontWeight: '700', fontSize: 15 },
  txtOn: { color: colors.text },
  hint: { color: colors.text3, fontSize: 12, marginTop: 6 },
});
