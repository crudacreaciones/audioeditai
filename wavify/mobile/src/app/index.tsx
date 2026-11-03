import * as Clipboard from 'expo-clipboard';
import { useEffect, useRef, useState } from 'react';
import { Animated, KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput,
  View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { api } from '../api/client';
import type { Bitrate, Job } from '../api/types';
import { Button } from '../components/Button';
import { Logo } from '../components/Logo';
import { Progress } from '../components/Progress';
import { QualityPicker } from '../components/QualityPicker';
import { TrackCard } from '../components/TrackCard';
import { useWavify } from '../hooks/useWavify';
import { saveMp3 } from '../lib/save';
import { isWorking } from '../lib/stages';
import { colors, radius } from '../theme';

function fmtSize(bytes: number) {
  return `${(bytes / 1024 / 1024).toLocaleString('es-ES', { maximumFractionDigits: 1 })} MB`;
}

export default function Home() {
  const [link, setLink] = useState('');
  const [bitrate, setBitrate] = useState<Bitrate>(320);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveError, setSaveError] = useState('');
  const { state, start, cancel, retry, reset } = useWavify();
  const working = isWorking(state.stage);
  const fade = useRef(new Animated.Value(1)).current;

  const resultKey = working ? 'working' : state.stage;
  useEffect(() => {
    fade.setValue(0);
    Animated.timing(fade, { toValue: 1, duration: 220, useNativeDriver: Platform.OS !== 'web' }).start();
    setSaved(null);
    setSaveError('');
  }, [resultKey, fade]);

  const paste = async () => {
    const text = await Clipboard.getStringAsync();
    if (text) setLink(text.trim());
  };

  const submit = () => start(link, bitrate);

  const newSearch = () => { reset(); setLink(''); };

  const save = async (job: Job) => {
    if (!job.file) return;
    setSaving(true);
    setSaveError('');
    try {
      const r = await saveMp3(api.fileUrl(job.file.download_path), job.file.name);
      setSaved(r.location ? `Guardado en ${r.location.startsWith('content://') ? 'la carpeta elegida' : r.location}` : 'Listo para guardar');
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'No se pudo guardar el archivo.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'bottom']}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <Logo />
            <Text style={styles.tagline}>Tu música, lista para llevar</Text>
          </View>

          <View style={styles.inputWrap}>
            <TextInput
              testID="link-input" value={link} onChangeText={setLink} editable={!working}
              placeholder="Pega aquí un enlace de Spotify" placeholderTextColor={colors.text3}
              style={styles.input} autoCapitalize="none" autoCorrect={false} keyboardType="url"
              returnKeyType="search" onSubmitEditing={submit} accessibilityLabel="Enlace de Spotify"
            />
            {link && !working ? (
              <Pressable onPress={() => setLink('')} style={styles.inlineBtn} accessibilityLabel="Borrar enlace" testID="clear">
                <Text style={styles.inlineTxt}>✕</Text>
              </Pressable>
            ) : !working ? (
              <Pressable onPress={paste} style={styles.inlineBtn} accessibilityLabel="Pegar" testID="paste">
                <Text style={[styles.inlineTxt, { color: colors.accent }]}>PEGAR</Text>
              </Pressable>
            ) : null}
          </View>

          <QualityPicker value={bitrate} onChange={setBitrate} disabled={working} />

          <Button title="BUSCAR Y CONVERTIR" onPress={submit} disabled={!link.trim() || working} testID="go" />

          <Animated.View style={{ opacity: fade, gap: 14 }}>
            {working && (
              <>
                {state.job?.track && <TrackCard track={state.job.track} />}
                <Progress stage={state.stage} progress={state.progress} />
                <Button title="Cancelar" kind="ghost" onPress={cancel} testID="cancel" />
              </>
            )}

            {state.stage === 'ready' && state.job?.track && state.job.file && (
              <TrackCard track={state.job.track}>
                <View style={styles.badges}>
                  <View style={[styles.badge, styles.badgeOk]}><Text style={styles.badgeOkTxt} testID="availability">✓ Descargable</Text></View>
                  <View style={styles.badge}><Text style={styles.badgeTxt} testID="quality">MP3 · {state.job.file.bitrate_kbps} kbps</Text></View>
                  <View style={styles.badge}><Text style={styles.badgeTxt}>{fmtSize(state.job.file.size)}</Text></View>
                </View>
                {state.job.file.note ? <Text style={styles.note} testID="quality-note">{state.job.file.note}</Text> : null}
                {state.job.selected?.license && (
                  <Text style={styles.license}>
                    Fuente: {state.job.selected.provider_name} · Licencia{' '}
                    <Text style={styles.link} onPress={() => Linking.openURL(state.job!.selected!.license!.url)}>
                      {state.job.selected.license.name}
                    </Text>
                    {state.job.selected.license.notes ? ` · ${state.job.selected.license.notes}` : ''}
                  </Text>
                )}
                <Button title={saved ? 'GUARDADO ✓' : 'GUARDAR MP3'} onPress={() => save(state.job!)} loading={saving}
                  disabled={!!saved} testID="save" />
                {saved && <Text style={styles.savedTxt} testID="saved">{saved}</Text>}
                {saveError ? <Text style={styles.errTxt}>{saveError}</Text> : null}
                <Button title="Nueva búsqueda" kind="ghost" onPress={newSearch} testID="new" />
              </TrackCard>
            )}

            {state.stage === 'no_results' && (
              <>
                {state.job?.track && <TrackCard track={state.job.track} />}
                <View style={[styles.notice, styles.noticeWarn]} testID="no-results">
                  <Text style={styles.noticeTitle}>Sin versión descargable autorizada</Text>
                  <Text style={styles.noticeTxt}>{state.message}</Text>
                </View>
                <Button title="Nueva búsqueda" kind="secondary" onPress={newSearch} testID="new" />
              </>
            )}

            {state.stage === 'error' && (
              <>
                <View style={[styles.notice, styles.noticeErr]} testID="error">
                  <Text style={styles.noticeTitle}>No se ha podido completar</Text>
                  <Text style={styles.noticeTxt}>{state.message}</Text>
                </View>
                {state.retryable ? <Button title="REINTENTAR" kind="secondary" onPress={retry} testID="retry" /> : null}
              </>
            )}
          </Animated.View>

          <Text style={styles.footer}>
            Solo se usan fuentes que autorizan la descarga. WAVIFY no descarga audio de Spotify ni elude protecciones.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  scroll: { padding: 22, gap: 18, maxWidth: 560, width: '100%', alignSelf: 'center', flexGrow: 1 },
  header: { alignItems: 'center', gap: 10, marginTop: 24, marginBottom: 10 },
  tagline: { color: colors.text2, fontSize: 16 },
  inputWrap: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, borderRadius: radius.m,
    borderWidth: 1, borderColor: colors.border, paddingLeft: 16 },
  input: { flex: 1, color: colors.text, fontSize: 16, paddingVertical: 18 },
  inlineBtn: { paddingHorizontal: 16, paddingVertical: 18 },
  inlineTxt: { color: colors.text2, fontWeight: '800', fontSize: 13, letterSpacing: 1 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  badge: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill, backgroundColor: colors.surface2 },
  badgeTxt: { color: colors.text2, fontSize: 13, fontWeight: '600' },
  badgeOk: { backgroundColor: colors.accentDim },
  badgeOkTxt: { color: colors.accent, fontSize: 13, fontWeight: '700' },
  note: { color: colors.warn, fontSize: 13 },
  license: { color: colors.text3, fontSize: 12 },
  link: { color: colors.text2, textDecorationLine: 'underline' },
  savedTxt: { color: colors.accent, textAlign: 'center', fontSize: 13 },
  errTxt: { color: colors.danger, textAlign: 'center', fontSize: 13 },
  notice: { borderRadius: radius.m, padding: 16, gap: 6, borderWidth: 1 },
  noticeWarn: { backgroundColor: colors.warnDim, borderColor: 'rgba(245,184,74,0.35)' },
  noticeErr: { backgroundColor: colors.dangerDim, borderColor: 'rgba(255,92,122,0.35)' },
  noticeTitle: { color: colors.text, fontWeight: '700', fontSize: 15 },
  noticeTxt: { color: colors.text2, fontSize: 14, lineHeight: 20 },
  footer: { color: colors.text3, fontSize: 12, textAlign: 'center', marginTop: 'auto', paddingTop: 20 },
});
