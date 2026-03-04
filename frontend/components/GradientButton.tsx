import React from 'react';
import { Text, TouchableOpacity, StyleSheet, ViewStyle, TextStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

interface GradientButtonProps {
    title: string;
    onPress: () => void;
}

export default function GradientButton({ title, onPress }: GradientButtonProps) {
    return (
        <TouchableOpacity activeOpacity={0.85} onPress={onPress} style={styles.button}>
            <Text style={styles.text}>{title}</Text>
        </TouchableOpacity>
    );
}

const styles = StyleSheet.create({
    button: {
        paddingVertical: 16,
        borderRadius: 999, // pill shape
        alignItems: 'center',
        marginTop: 20,
        backgroundColor: '#3B5DA1', // Solid primary color

        shadowColor: '#3B5DA1',
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
