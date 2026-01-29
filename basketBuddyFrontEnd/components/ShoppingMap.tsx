import React from 'react';
import MapView, { Marker, Polyline, PROVIDER_GOOGLE } from 'react-native-maps';
import { StyleSheet } from 'react-native';
import { Colors } from '@/constants/theme';

interface ShoppingMapProps {
    userLocation: { lat: number; lng: number };
    shoppingList: any[];
}

export default function ShoppingMap({ userLocation, shoppingList }: ShoppingMapProps) {
    return (
        <MapView
            provider={PROVIDER_GOOGLE}
            style={styles.map}
            initialRegion={{
                latitude: userLocation.lat,
                longitude: userLocation.lng,
                latitudeDelta: 0.1,
                longitudeDelta: 0.1,
            }}
        >
            {/* User Home Location */}
            <Marker
                coordinate={{ latitude: userLocation.lat, longitude: userLocation.lng }}
                title="Your Location"
                pinColor={Colors.primary}
            />

            {/* Store Markers */}
            {shoppingList.map((store, idx) => (
                <Marker
                    key={idx}
                    coordinate={{ latitude: store.coordinates.lat, longitude: store.coordinates.lng }}
                    title={store.store}
                    description={store.address}
                    pinColor="#EAB308"
                />
            ))}

            {/* Route Polyline */}
            <Polyline
                coordinates={[
                    { latitude: userLocation.lat, longitude: userLocation.lng },
                    ...shoppingList.map(s => ({ latitude: s.coordinates.lat, longitude: s.coordinates.lng })),
                    { latitude: userLocation.lat, longitude: userLocation.lng }
                ]}
                strokeColor={Colors.primary}
                strokeWidth={3}
            />
        </MapView>
    );
}

const styles = StyleSheet.create({
    map: {
        ...StyleSheet.absoluteFillObject,
    }
});
