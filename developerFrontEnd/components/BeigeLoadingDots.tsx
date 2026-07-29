import React, { useEffect, useRef } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";

export default function BeigeLoadingDots({
    size = 6,
    gap = 6,
    bounce = 5,
}: {
    size?: number;
    gap?: number;
    bounce?: number;
}) {
    const a1 = useRef(new Animated.Value(0)).current;
    const a2 = useRef(new Animated.Value(0)).current;
    const a3 = useRef(new Animated.Value(0)).current;

    useEffect(() => {
        const makeLoop = (a: Animated.Value, delay: number) =>
            Animated.loop(
                Animated.sequence([
                    Animated.delay(delay),
                    Animated.timing(a, {
                        toValue: 1,
                        duration: 380,
                        easing: Easing.inOut(Easing.cubic),
                        useNativeDriver: true,
                    }),
                    Animated.timing(a, {
                        toValue: 0,
                        duration: 380,
                        easing: Easing.inOut(Easing.cubic),
                        useNativeDriver: true,
                    }),
                ])
            );

        const loop1 = makeLoop(a1, 0);
        const loop2 = makeLoop(a2, 120);
        const loop3 = makeLoop(a3, 240);

        Animated.parallel([loop1, loop2, loop3]).start();

        return () => {
            loop1.stop();
            loop2.stop();
            loop3.stop();
            a1.setValue(0);
            a2.setValue(0);
            a3.setValue(0);
        };
    }, [a1, a2, a3]);

    const dotStyle = (a: Animated.Value) => ({
        transform: [
            {
                translateY: a.interpolate({
                    inputRange: [0, 1],
                    outputRange: [0, -bounce],
                }),
            },
        ],
        opacity: a.interpolate({
            inputRange: [0, 1],
            outputRange: [0.45, 1],
        }),
    });

    return (
        <View style={[styles.dotsInline, { columnGap: gap }]}>
            <Animated.View
                style={[styles.dot, { width: size, height: size, borderRadius: size / 2 }, dotStyle(a1)]}
            />
            <Animated.View
                style={[styles.dot, { width: size, height: size, borderRadius: size / 2 }, dotStyle(a2)]}
            />
            <Animated.View
                style={[styles.dot, { width: size, height: size, borderRadius: size / 2 }, dotStyle(a3)]}
            />
        </View>
    );
}

const styles = StyleSheet.create({
    dotsInline: {
        flexDirection: "row",
        alignItems: "center",
        marginLeft: 10, // space after title text
        paddingBottom: 12, // baseline tweak to align with large text
    },
    dot: {
        backgroundColor: "#000000", // black
    },
});
