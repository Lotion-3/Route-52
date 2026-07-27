import React, { useMemo, useRef, useCallback } from 'react';
import { StyleSheet, View } from 'react-native';
import MapView, { Marker, Polyline, PROVIDER_GOOGLE } from 'react-native-maps';
import { Colors } from '@/constants/theme';

interface ShoppingMapProps {
    userLocation: { lat: number; lng: number };
    shoppingList: any[];
}

// Padding around the fitted route, as a fraction of the span on each side.
const EDGE_PADDING = 0.35;
// Floor on the visible span so a single nearby store doesn't zoom to street level.
const MIN_DELTA = 0.02;

export default function ShoppingMap({ userLocation, shoppingList }: ShoppingMapProps) {
    const mapRef = useRef<MapView | null>(null);

    // Tolerate a store with missing / non-finite coordinates rather than
    // rendering a marker at (undefined, undefined), which crashes the map.
    const stops = useMemo(
        () =>
            (shoppingList ?? [])
                .map((s) => ({
                    store: s?.store,
                    address: s?.address,
                    latitude: Number(s?.coordinates?.lat),
                    longitude: Number(s?.coordinates?.lng),
                }))
                .filter((s) => Number.isFinite(s.latitude) && Number.isFinite(s.longitude)),
        [shoppingList],
    );

    const origin = useMemo(
        () => ({ latitude: userLocation.lat, longitude: userLocation.lng }),
        [userLocation.lat, userLocation.lng],
    );

    const routeCoords = useMemo(
        () => [origin, ...stops.map(({ latitude, longitude }) => ({ latitude, longitude })), origin],
        [origin, stops],
    );

    /**
     * Region containing the user AND every stop.
     *
     * This used to be a hardcoded `latitudeDelta: 0.05` (~5 km) centred on the
     * user, so anyone whose stores were further out — rural users especially —
     * saw an apparently empty map with the whole route off-screen and no
     * indication it was there.
     */
    const region = useMemo(() => {
        const lats = [origin.latitude, ...stops.map((s) => s.latitude)];
        const lngs = [origin.longitude, ...stops.map((s) => s.longitude)];
        const minLat = Math.min(...lats), maxLat = Math.max(...lats);
        const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
        return {
            latitude: (minLat + maxLat) / 2,
            longitude: (minLng + maxLng) / 2,
            latitudeDelta: Math.max(MIN_DELTA, (maxLat - minLat) * (1 + EDGE_PADDING * 2)),
            longitudeDelta: Math.max(MIN_DELTA, (maxLng - minLng) * (1 + EDGE_PADDING * 2)),
        };
    }, [origin, stops]);

    // Re-fit once the map is ready. `initialRegion` is applied only on first
    // mount, so it wouldn't re-apply when the plan (and route) changes.
    const handleReady = useCallback(() => {
        if (routeCoords.length > 2) {
            mapRef.current?.fitToCoordinates(routeCoords, {
                edgePadding: { top: 48, right: 48, bottom: 48, left: 48 },
                animated: false,
            });
        }
    }, [routeCoords]);

    return (
        <View style={styles.container}>
            <MapView
                ref={mapRef}
                provider={PROVIDER_GOOGLE}
                style={styles.map}
                initialRegion={region}
                onMapReady={handleReady}
            >
                {/* User Location */}
                <Marker
                    coordinate={origin}
                    title="Your Location"
                    pinColor={Colors.primary}
                />

                {/* Store Markers */}
                {stops.map((store, idx) => (
                    <Marker
                        key={`${store.store}-${idx}`}
                        coordinate={{ latitude: store.latitude, longitude: store.longitude }}
                        title={store.store}
                        description={store.address}
                        pinColor="#EAB308"
                    />
                ))}

                {stops.length > 0 && (
                    <Polyline
                        coordinates={routeCoords}
                        strokeWidth={4}
                        strokeColor={Colors.primary}
                    />
                )}
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
