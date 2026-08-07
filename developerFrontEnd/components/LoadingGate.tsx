import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, Animated, Easing } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Logo from '@/components/Logo';

/**
 * Full-screen gate overlay shown for `durationMs` (default 5s) when /search
 * mounts. Purely perceptual: a fast-filling progress bar + rotating
 * "finding stores / checking prices" copy block the form while the backend
 * prewarm (fired on /location) mints the Walmart/Target cookies in the
 * background. The bar is NOT tied to real progress — it just makes the wait feel
 * productive. Covers the screen and swallows taps until it calls onDone().
 */

interface LoadingGateProps {
    durationMs?: number;
    onDone?: () => void;
}

// Copy swaps as the bar crosses each threshold, so the messages feel tied to it.
const STAGES = [
    { at: 0.0, label: 'Locating stores near you…' },
    { at: 0.35, label: 'Checking live prices…' },
    { at: 0.7, label: 'Comparing Walmart, Target & more…' },
    { at: 0.92, label: 'Almost ready…' },
];

export default function LoadingGate({ durationMs = 5000, onDone }: LoadingGateProps) {
    const progress = useRef(new Animated.Value(0)).current;
    const [percent, setPercent] = useState(0);
    const [stage, setStage] = useState(STAGES[0].label);

    useEffect(() => {
        const d = durationMs;
        // Fast burst out of the gate, two slowing crawls, then a settle — the
        // four legs sum to durationMs.
        Animated.sequence([
            Animated.timing(progress, { toValue: 0.65, duration: d * 0.18, easing: Easing.out(Easing.quad), useNativeDriver: false }),
            Animated.timing(progress, { toValue: 0.85, duration: d * 0.28, easing: Easing.linear, useNativeDriver: false }),
            Animated.timing(progress, { toValue: 0.96, duration: d * 0.34, easing: Easing.linear, useNativeDriver: false }),
            Animated.timing(progress, { toValue: 1, duration: d * 0.20, easing: Easing.in(Easing.quad), useNativeDriver: false }),
        ]).start();

        const listenerId = progress.addListener(({ value }) => {
            setPercent(Math.round(value * 100));
            const s = [...STAGES].reverse().find((st) => value >= st.at);
            if (s) setStage(s.label);
        });

        const timer = setTimeout(() => onDone?.(), durationMs);

        return () => {
            progress.removeListener(listenerId);
            progress.stopAnimation();
            clearTimeout(timer);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [durationMs]);

    const width = progress.interpolate({
        inputRange: [0, 1],
        outputRange: ['0%', '100%'],
    });

    return (
        <View style={styles.overlay} pointerEvents="auto">
            <LinearGradient
                colors={['#FFFFFF', '#F3EDE4']}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 1 }}
                style={StyleSheet.absoluteFill}
            />
            <View style={styles.center}>
                <Logo size={88} />
                <Text style={styles.title}>Building your plan</Text>
                <Text style={styles.sub}>{stage}</Text>

                <View style={styles.barTrack}>
                    <Animated.View style={[styles.barFillWrap, { width }]}>
                        <LinearGradient
                            colors={['#f7a14e', '#ee7422']}
                            start={{ x: 0, y: 0 }}
                            end={{ x: 1, y: 0 }}
                            style={styles.barFill}
                        />
                    </Animated.View>
                </View>
                <Text style={styles.percent}>{percent}%</Text>
            </View>
        </View>
    );
}

const styles = StyleSheet.create({
    overlay: {
        ...StyleSheet.absoluteFillObject,
        zIndex: 1000,
        elevation: 1000,
    },
    center: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: 32,
    },
    title: {
        fontSize: 24,
        fontWeight: '700',
        color: '#1A1A1A',
        fontFamily: 'Fraunces-Bold',
        marginTop: 20,
    },
    sub: {
        fontSize: 15,
        color: '#6B7280',
        textAlign: 'center',
        marginTop: 8,
        marginBottom: 28,
        minHeight: 20,
        fontFamily: 'WorkSans-Regular',
    },
    barTrack: {
        width: '100%',
        maxWidth: 360,
        height: 10,
        borderRadius: 999,
        backgroundColor: '#E5E7EB',
        overflow: 'hidden',
    },
    barFillWrap: {
        height: '100%',
    },
    barFill: {
        flex: 1,
        borderRadius: 999,
    },
    percent: {
        marginTop: 12,
        fontSize: 14,
        fontWeight: '600',
        color: '#9CA3AF',
        fontFamily: 'WorkSans-Regular',
    },
});
