import React from 'react';
import { Text, TouchableOpacity, StyleSheet, ViewStyle, TextStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

interface GradientButtonProps {
    title: string;
    onPress: () => void;
    style?: any;
}

export default function GradientButton({ title, onPress, style }: GradientButtonProps) {
    return (
        <TouchableOpacity activeOpacity={0.85} onPress={onPress} style={style}>
            <LinearGradient
                colors={['#FFA54F', '#E8821E']}
                start={{ x: 0, y: 0 }}
                end={{ x: 0, y: 1 }}
                style={[styles.button, style]}
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
        width: '100%',

        shadowColor: '#000000',
        shadowOpacity: 0.25,
        shadowRadius: 5,
        shadowOffset: { width: 0, height: 3 },
        elevation: 5,
    } as ViewStyle,

    text: {
        color: '#fff',
        fontSize: 17,
        fontWeight: '700',
        letterSpacing: 0.3,
    } as TextStyle,
});
