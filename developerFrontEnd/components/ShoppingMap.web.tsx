import React from 'react';
import { View, StyleSheet, TouchableOpacity, Text, Linking } from 'react-native';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { Colors } from '@/constants/theme';
import GradientButton from '@/components/GradientButton';

interface ShoppingMapProps {
    userLocation: { lat: number; lng: number };
    shoppingList: any[];
}

export default function ShoppingMap({ userLocation, shoppingList }: ShoppingMapProps) {
    const origin = `${userLocation.lat},${userLocation.lng}`;
    const destination = origin;
    // Skip stores with missing/non-finite coordinates — `${undefined},${undefined}`
    // used to be interpolated straight into the waypoints and broke the link.
    const stops = (shoppingList ?? []).filter(
        (s) => Number.isFinite(Number(s?.coordinates?.lat)) && Number.isFinite(Number(s?.coordinates?.lng)),
    );
    const waypoints = stops.map(s => `${s.coordinates.lat},${s.coordinates.lng}`).join('|');
    const url =
        `https://www.google.com/maps/dir/?api=1&origin=${origin}&destination=${destination}` +
        (waypoints ? `&waypoints=${encodeURIComponent(waypoints)}` : '') +
        `&travelmode=driving`;

    // For web, since react-native-maps doesn't work without keys, 
    // we'll use a clean OpenStreetMap embed or a styled placeholder that's actually useful.
    // Here we use a better styled placeholder with the list of coordinates and a link.
    return (
        <View style={styles.webMapPlaceholder}>
            <View style={styles.mapHeader}>
                <IconSymbol name="map.fill" size={24} color={Colors.primary} />
                <Text style={styles.mapTitle}>Interactive Route Map</Text>
            </View>
            <Text style={styles.webMapText}>
                Your optimized route involves {stops.length} store{stops.length === 1 ? '' : 's'} starting from{' '}
                {userLocation.lat.toFixed(4)}, {userLocation.lng.toFixed(4)}.
            </Text>
            <View style={styles.storeMiniList}>
                {stops.map((s, i) => (
                    <Text key={`${s.store}-${i}`} style={styles.storeMiniItem}>📍 {s.store}</Text>
                ))}
            </View>
            <GradientButton
                title="View Full Route on Google Maps"
                onPress={() => Linking.openURL(url)}
                style={{ width: 'auto', alignSelf: 'center', paddingHorizontal: 24, paddingVertical: 12 }}
            />
        </View>
    );
}

const styles = StyleSheet.create({
    webMapPlaceholder: {
        flex: 1,
        backgroundColor: '#FFFFFF',
        justifyContent: 'center',
        alignItems: 'center',
        padding: 30,
        borderRadius: 24,
    },
    mapHeader: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: 16,
    },
    mapTitle: {
        fontSize: 18,
        fontWeight: 'bold',
        color: Colors.text,
        marginLeft: 10,
    },
    webMapText: {
        fontSize: 14,
        color: Colors.textLight,
        textAlign: 'center',
        marginBottom: 20,
        lineHeight: 20,
    },
    storeMiniList: {
        width: '100%',
        backgroundColor: '#F7F2EA',
        padding: 16,
        borderRadius: 12,
        marginBottom: 24,
    },
    storeMiniItem: {
        fontSize: 13,
        color: Colors.text,
        marginBottom: 6,
        fontWeight: '500',
    },
});
