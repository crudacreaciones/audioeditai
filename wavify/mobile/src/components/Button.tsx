import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';

import { colors, radius } from '../theme';

type Props = { title: string; onPress: () => void; kind?: 'primary' | 'secondary' | 'ghost'; disabled?: boolean;
  loading?: boolean; testID?: string };

export function Button({ title, onPress, kind = 'primary', disabled, loading, testID }: Props) {
  return (
    <Pressable onPress={onPress} disabled={disabled || loading} testID={testID} accessibilityRole="button"
      accessibilityState={{ disabled: disabled || loading }}
      style={({ pressed }) => [styles.base, styles[kind], (disabled || loading) && styles.disabled, pressed && styles.pressed]}>
      {loading ? <ActivityIndicator color={kind === 'primary' ? '#04140A' : colors.text} />
        : <Text style={[styles.text, kind === 'primary' ? styles.textPrimary : styles.textOther]}>{title}</Text>}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: { minHeight: 58, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 22 },
  primary: { backgroundColor: colors.accent },
  secondary: { backgroundColor: colors.surface2, borderWidth: 1, borderColor: colors.border },
  ghost: { backgroundColor: 'transparent', minHeight: 44 },
  disabled: { opacity: 0.45 },
  pressed: { transform: [{ scale: 0.98 }], opacity: 0.9 },
  text: { fontSize: 16, fontWeight: '800', letterSpacing: 1 },
  textPrimary: { color: '#04140A' },
  textOther: { color: colors.text },
});
