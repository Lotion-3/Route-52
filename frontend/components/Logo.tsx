import React from 'react';
import { StyleSheet, ViewStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';

interface LogoProps {
    size?: number;
}

export default function Logo({ size = 60 }: LogoProps) {
    const iconSize = (size / 60) * 26;

    return (
        <LinearGradient
            colors={['#2563EB', '#3B82F6']}
            style={[styles.logo, { width: size, height: size, borderRadius: size / 2 }]}
        >
            <Ionicons name="basket-outline" size={iconSize} color="#fff" />
        </LinearGradient>
    );
}

const styles = StyleSheet.create({
    logo: {
        alignItems: 'center',
        justifyContent: 'center',
        shadowColor: '#000',
        shadowOpacity: 0.35,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 6 },
        elevation: 6,
        alignSelf: 'center',
    } as ViewStyle,
});
