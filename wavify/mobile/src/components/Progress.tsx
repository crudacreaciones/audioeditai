import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { STEPS, stepIndex, type UiStage } from '../lib/stages';
import { colors, radius } from '../theme';

export function Progress({ stage, progress }: { stage: UiStage; progress: number }) {
  const current = stepIndex(stage);
  return (
    <View style={styles.card} testID="progress">
      <View style={styles.bar}>
        <View style={[styles.fill, { width: `${Math.max(4, Math.round(progress * 100))}%` }]} />
      </View>
      {STEPS.map((s, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <View key={s.stage} style={styles.step}>
            <View style={[styles.dot, done && styles.dotDone, active && styles.dotActive]}>
              {active ? <ActivityIndicator size="small" color={colors.accent} /> : done ? <Text style={styles.check}>✓</Text> : null}
            </View>
            <Text style={[styles.label, (done || active) && styles.labelOn]} testID={active ? 'current-step' : undefined}>
              {s.label}{active ? '…' : ''}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.m, padding: 18, gap: 10, borderWidth: 1, borderColor: colors.border },
  bar: { height: 6, backgroundColor: colors.surface2, borderRadius: radius.pill, overflow: 'hidden', marginBottom: 6 },
  fill: { height: '100%', backgroundColor: colors.accent, borderRadius: radius.pill },
  step: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  dot: { width: 24, height: 24, borderRadius: 12, borderWidth: 1.5, borderColor: colors.border, alignItems: 'center', justifyContent: 'center' },
  dotDone: { backgroundColor: colors.accent, borderColor: colors.accent },
  dotActive: { borderColor: 'transparent' },
  check: { color: '#04140A', fontWeight: '900', fontSize: 13 },
  label: { color: colors.text3, fontSize: 15 },
  labelOn: { color: colors.text },
});
