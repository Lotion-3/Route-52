import React from 'react';
import { StyleSheet, View } from 'react-native';
import MapView, { Marker, Polyline, PROVIDER_GOOGLE } from 'react-native-maps';
import { Colors } from '@/constants/theme';

interface ShoppingMapProps {
    userLocation: { lat: number; lng: number };
    shoppingList: any[];
}

export default function ShoppingMap({ userLocation, shoppingList }: ShoppingMapProps) {
    const routeCoords = [
        { latitude: userLocation.lat, longitude: userLocation.lng },
        ...shoppingList.map(s => ({
            latitude: s.coordinates.lat,
            longitude: s.coordinates.lng,
        })),
        { latitude: userLocation.lat, longitude: userLocation.lng } // Return home
    ];

    return (
        <View style={styles.container}>
            <MapView
                provider={PROVIDER_GOOGLE}
                style={styles.map}
                initialRegion={{
                    latitude: userLocation.lat,
                    longitude: userLocation.lng,
                    latitudeDelta: 0.05,
                    longitudeDelta: 0.05,
                }}
            >
                {/* User Location */}
                <Marker
                    coordinate={{ latitude: userLocation.lat, longitude: userLocation.lng }}
                    title="Your Location"
                    pinColor={Colors.primary}
                />

                {/* Store Markers */}
                {shoppingList.map((store, idx) => (
                    <Marker
                        key={idx}
                        coordinate={{
                            latitude: store.coordinates.lat,
                            longitude: store.coordinates.lng,
                        }}
                        title={store.store}
                        description={store.address}
                        pinColor="#EAB308"
                    />
                ))}

                <Polyline
                    coordinates={routeCoords}
                    strokeWidth={4}
                    strokeColor={Colors.primary}
                />
            </MapView>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        borderRadius: 16,
        overflow: "hidden",
    },
    map: {
        flex: 1,
    },
});
