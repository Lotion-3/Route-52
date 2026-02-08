import React from 'react';
import { StyleSheet, ViewStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';

export default function Logo() {
    return (
        <LinearGradient
            colors={['#2563EB', '#3B82F6']}
            style={styles.logo}
        >
            <Ionicons name="basket-outline" size={26} color="#fff" />
        </LinearGradient>
    );
}

const styles = StyleSheet.create({
    logo: {
        width: 60,
        height: 60,
        borderRadius: 30,
        alignItems: 'center',
        justifyContent: 'center',
        shadowColor: '#000',
        shadowOpacity: 0.35,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 6 },
        elevation: 6,
        alignSelf: 'center',
        marginBottom: 16,
    } as ViewStyle,
});
