import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

export default function BarcodeScreen() {
    const router = useRouter();

    return (
        <View style={styles.container}>
            <TouchableOpacity style={styles.backButton} onPress={() => router.back()}>
                <Ionicons name="arrow-back" size={24} color="#1E293B" />
                <Text style={styles.backText}>Back</Text>
            </TouchableOpacity>

            <View style={styles.content}>
                <Text style={styles.title}>Your Coupon Barcode</Text>
                <Text style={styles.subtitle}>Scan this at the checkout to apply your discount.</Text>

                <View style={styles.barcodeWrapper}>
                    {/* Simplified Barcode Representation */}
                    <View style={styles.barcode}>
                        {Array.from({ length: 25 }).map((_, i) => (
                            <View
                                key={i}
                                style={[
                                    styles.bar,
                                    {
                                        width: Math.random() > 0.5 ? 2 : 4,
                                        marginRight: Math.random() > 0.7 ? 1 : 2,
                                        backgroundColor: i % 3 === 0 ? '#aaa' : '#000'
                                    }
                                ]}
                            />
                        ))}
                    </View>
                    <Text style={styles.barcodeNumber}>R52-DEMO-2024-X99</Text>
                </View>

                <TouchableOpacity style={styles.doneButton} onPress={() => router.back()}>
                    <Text style={styles.doneButtonText}>Done</Text>
                </TouchableOpacity>
            </View>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#F3F0E9', // Warmer background
        padding: 24,
        paddingTop: 60,
    },
    backButton: {
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: 40,
    },
    backText: {
        fontSize: 16,
        marginLeft: 8,
        fontWeight: '600',
        color: '#1E293B',
    },
    content: {
        alignItems: 'center',
        justifyContent: 'center',
        flex: 1,
    },
    title: {
        fontSize: 24,
        fontWeight: '700',
        color: '#1E293B',
        marginBottom: 8,
    },
    subtitle: {
        fontSize: 16,
        color: '#64748B',
        textAlign: 'center',
        marginBottom: 40,
        paddingHorizontal: 20,
    },
    barcodeWrapper: {
        backgroundColor: '#FFFFFF',
        padding: 30,
        borderRadius: 20,
        alignItems: 'center',
        shadowColor: '#000',
        shadowOpacity: 0.1,
        shadowRadius: 10,
        shadowOffset: { width: 0, height: 4 },
        elevation: 5,
        marginBottom: 40,
    },
    barcode: {
        flexDirection: 'row',
        height: 120,
        alignItems: 'stretch',
        marginBottom: 20,
    },
    bar: {
        height: '100%',
    },
    barcodeNumber: {
        fontSize: 14,
        letterSpacing: 4,
        color: '#1E293B',
        fontWeight: '600',
    },
    doneButton: {
        backgroundColor: '#3B5DA1',
        paddingVertical: 16,
        paddingHorizontal: 40,
        borderRadius: 12,
    },
    doneButtonText: {
        color: '#FFFFFF',
        fontSize: 16,
        fontWeight: '700',
    },
});
