import React from 'react';
import { View, StyleSheet, TouchableOpacity, Text, Linking } from 'react-native';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { Colors } from '@/constants/theme';

interface ShoppingMapProps {
    userLocation: { lat: number; lng: number };
    shoppingList: any[];
}

export default function ShoppingMap({ userLocation, shoppingList }: ShoppingMapProps) {
    const origin = `${userLocation.lat},${userLocation.lng}`;
    const destination = origin;
    const waypoints = shoppingList.map(s => `${s.coordinates.lat},${s.coordinates.lng}`).join('|');
    const url = `https://www.google.com/maps/dir/?api=1&origin=${origin}&destination=${destination}&waypoints=${waypoints}&travelmode=driving`;

    return (
        <View style={styles.webMapPlaceholder}>
            <IconSymbol name="map.fill" size={40} color={Colors.textLight} />
            <Text style={styles.webMapText}>Map view is best experienced on iOS/Android</Text>
            <TouchableOpacity
                style={styles.openMapsButton}
                onPress={() => Linking.openURL(url)}
            >
                <Text style={styles.openMapsButtonText}>Open in Google Maps</Text>
            </TouchableOpacity>
        </View>
    );
}

const styles = StyleSheet.create({
    webMapPlaceholder: {
        flex: 1,
        backgroundColor: Colors.card,
        justifyContent: 'center',
        alignItems: 'center',
        padding: 20,
    },
    webMapText: {
        fontSize: 14,
        color: Colors.textLight,
        textAlign: 'center',
        marginTop: 12,
        marginBottom: 16,
    },
    openMapsButton: {
        backgroundColor: Colors.primary,
        paddingHorizontal: 20,
        paddingVertical: 10,
        borderRadius: 8,
    },
    openMapsButtonText: {
        color: '#fff',
        fontWeight: '600',
        fontSize: 14,
    }
});
