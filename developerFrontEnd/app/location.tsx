import React, { useState, useEffect, useRef } from 'react';
import {
    View, Text, TextInput, StyleSheet, TouchableOpacity,
    KeyboardAvoidingView, Platform, ScrollView,
} from 'react-native';
import { useRouter, Stack } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import Logo from '@/components/Logo';
import GradientButton from '@/components/GradientButton';
import TopBanner from '@/components/TopBanner';
import { prewarm, autocompleteAddress } from '@/services/api';
import { notify } from '@/services/notify';

/**
 * Step 1 of the meal-plan flow: collect location + shopping time FIRST.
 *
 * The moment the user continues, we fire prewarm(location, time) so the backend
 * resolves the nearby stores and warms ONLY the chains actually found in range
 * (the ~8s-per-store warm) in the background, then push to /search — which shows
 * a ~5s gate overlay on mount (LoadingGate) so the warm is hidden behind a
 * fast-filling progress bar. By the time they hit "Generate Plan", the warm is
 * already done. Nothing is warmed before this point — an address suggestion tap
 * used to eagerly warm both Walmart + Target with the isochrone still unknown,
 * which meant warming stores that might not even be near the user.
 */
export default function LocationScreen() {
    const router = useRouter();
    const [location, setLocation] = useState('');
    const [time, setTime] = useState('3');
    const [suggestions, setSuggestions] = useState<string[]>([]);
    // Skip the next fetch after the user taps a suggestion (which sets the full
    // address into `location` and would otherwise re-trigger the dropdown).
    const suppressFetch = useRef(false);

    // Debounced address autocomplete: fetch suggestions ~300ms after typing stops.
    // The in-flight request is aborted when the query changes, so a slow earlier
    // keystroke can't resolve late and overwrite newer suggestions.
    useEffect(() => {
        if (suppressFetch.current) {
            suppressFetch.current = false;
            return;
        }
        const q = location.trim();
        if (q.length < 3) {
            setSuggestions([]);
            return;
        }
        const controller = new AbortController();
        let cancelled = false;
        const t = setTimeout(async () => {
            const next = await autocompleteAddress(q, controller.signal);
            if (!cancelled) setSuggestions(next);
        }, 300);
        return () => {
            cancelled = true;
            clearTimeout(t);
            controller.abort();
        };
    }, [location]);

    const selectSuggestion = (s: string) => {
        suppressFetch.current = true;
        setLocation(s);
        setSuggestions([]);
        // No warming here — the isochrone (and therefore which stores are even
        // in range) isn't known until Continue, where prewarm(location, time)
        // resolves it and warms only what was actually found.
    };

    const handleContinue = () => {
        if (!location.trim()) {
            // Bare alert() is web-only — on iOS/Android it's undefined, so
            // submitting an empty address used to do nothing at all.
            notify('Location needed', 'Please enter your location so we can find stores near you.');
            return;
        }
        // Fire-and-forget: resolve nearby stores + warm the browser sessions now,
        // hiding the latency. Pass time so the store-isochrone cache matches generate.
        prewarm(location, time);
        // /search shows a ~5s gate overlay on mount (LoadingGate), so the warm
        // runs behind a fast-filling progress bar before the form is usable.
        router.push({ pathname: '/search', params: { location, time } });
    };

    return (
        <KeyboardAvoidingView
            style={{ flex: 1 }}
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
            <Stack.Screen options={{ headerShown: false }} />
            <TopBanner />
            <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: 92 }]} keyboardShouldPersistTaps="handled">
                <View style={styles.headerWrap}>
                    <View style={{ marginTop: -20 }}>
                        <Logo size={240} />
                    </View>
                    <Text style={styles.header}>Where are you shopping?</Text>
                    <Text style={styles.sub}>
                        We'll find the stores near you and start checking live prices
                        while you set up your plan.
                    </Text>
                </View>

                <View style={styles.section}>
                    <View style={styles.card}>
                        <Text style={styles.label}>Your Location</Text>
                        <View style={styles.inputRow}>
                            <Ionicons name="location-outline" size={18} color="#9CA3AF" />
                            <TextInput
                                placeholder="Address or Zip Code"
                                placeholderTextColor="#9CA3AF"
                                style={styles.iconInput}
                                value={location}
                                onChangeText={setLocation}
                                autoFocus
                                returnKeyType="next"
                                onSubmitEditing={handleContinue}
                            />
                        </View>
                        {suggestions.length > 0 && (
                            <View style={styles.suggestBox}>
                                {suggestions.map((s) => (
                                    <TouchableOpacity
                                        key={s}
                                        style={styles.suggestItem}
                                        onPress={() => selectSuggestion(s)}
                                    >
                                        <Ionicons name="location-outline" size={15} color="#9CA3AF" />
                                        <Text style={styles.suggestText} numberOfLines={1}>{s}</Text>
                                    </TouchableOpacity>
                                ))}
                            </View>
                        )}
                    </View>
                </View>

                <View style={styles.section}>
                    <View style={styles.card}>
                        <Text style={styles.label}>Shopping Time (hrs)</Text>
                        <View style={styles.inputRow}>
                            <Ionicons name="time-outline" size={18} color="#9CA3AF" />
                            <TextInput
                                placeholder="3"
                                placeholderTextColor="#9CA3AF"
                                style={styles.iconInput}
                                keyboardType="numeric"
                                value={time}
                                onChangeText={setTime}
                            />
                        </View>
                    </View>
                </View>

                <View style={styles.buttonWrap}>
                    <GradientButton title="Continue →" onPress={handleContinue} />
                </View>
            </ScrollView>
        </KeyboardAvoidingView>
    );
}

const styles = StyleSheet.create({
    scroll: {
        flexGrow: 1,
        padding: 20,
        paddingTop: 2,
    },
    headerWrap: {
        alignItems: 'center',
        marginBottom: 24,
    },
    header: {
        fontSize: 24,
        fontWeight: '700',
        color: '#1A1A1A',
        fontFamily: 'Fraunces-Bold',
        textAlign: 'center',
        marginTop: -16,
    },
    sub: {
        fontSize: 14,
        color: '#6B7280',
        textAlign: 'center',
        marginTop: 4,
        paddingHorizontal: 12,
    },
    section: {
        marginBottom: 16,
    },
    card: {
        backgroundColor: '#FFFFFF',
        borderRadius: 16,
        padding: 16,
        borderWidth: 1,
        borderColor: '#E5E7EB',
    },
    label: {
        fontSize: 14,
        fontWeight: '600',
        color: '#374151',
        marginBottom: 8,
    },
    inputRow: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: '#F9FAFB',
        borderRadius: 12,
        paddingHorizontal: 12,
        borderWidth: 1,
        borderColor: '#E5E7EB',
    },
    iconInput: {
        flex: 1,
        paddingVertical: 12,
        paddingLeft: 8,
        fontSize: 16,
        color: '#1A1A1A',
    },
    suggestBox: {
        marginTop: 8,
        backgroundColor: '#FFFFFF',
        borderRadius: 12,
        borderWidth: 1,
        borderColor: '#E5E7EB',
        overflow: 'hidden',
    },
    suggestItem: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 12,
        paddingHorizontal: 12,
        borderBottomWidth: StyleSheet.hairlineWidth,
        borderBottomColor: '#F0F0F0',
        gap: 8,
    },
    suggestText: {
        flex: 1,
        fontSize: 14,
        color: '#374151',
    },
    buttonWrap: {
        marginTop: 8,
    },
});
