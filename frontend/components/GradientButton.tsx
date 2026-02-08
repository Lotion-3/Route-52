import React from 'react';
import { Text, TouchableOpacity, StyleSheet, ViewStyle, TextStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

interface GradientButtonProps {
    title: string;
    onPress: () => void;
}

export default function GradientButton({ title, onPress }: GradientButtonProps) {
    return (
        <TouchableOpacity activeOpacity={0.85} onPress={onPress}>
            <LinearGradient
                colors={['#2563EB', '#3B82F6']} // deep blue -> soft blue
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 1 }}
                style={styles.button}
            >
                <Text style={styles.text}>{title}</Text>
            </LinearGradient>
        </TouchableOpacity>
    );
}

const styles = StyleSheet.create({
    button: {
        paddingVertical: 16,
        borderRadius: 999, // pill shape
        alignItems: 'center',
        marginTop: 20,

        shadowColor: '#2563EB',
        shadowOpacity: 0.35,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 6 },

        elevation: 6,
    } as ViewStyle, // Explicitly casting to ViewStyle for TS compatibility if needed

    text: {
        color: '#fff',
        fontSize: 17,
        fontWeight: '700',
        letterSpacing: 0.3,
    } as TextStyle,
});
