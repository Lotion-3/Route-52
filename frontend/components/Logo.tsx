import React from 'react';
import { StyleSheet, ImageStyle, Image } from 'react-native';

interface LogoProps {
    size?: number;
}

export default function Logo({ size = 72 }: LogoProps) {
    return (
        <Image
            source={require('../assets/images/logo.png')}
            style={[styles.logo, { width: size, height: size }]}
            resizeMode="contain"
        />
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
    } as ImageStyle,
});
