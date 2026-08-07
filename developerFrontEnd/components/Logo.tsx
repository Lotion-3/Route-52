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
        alignSelf: 'center',
    } as ImageStyle,
});
