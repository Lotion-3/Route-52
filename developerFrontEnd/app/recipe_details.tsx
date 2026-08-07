import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, SafeAreaView } from 'react-native';
import { Stack, useRouter, useLocalSearchParams } from 'expo-router';
import { Colors } from '@/constants/theme';
import { Ionicons } from '@expo/vector-icons';

export default function RecipeDetailsScreen() {
    const router = useRouter();
    const params = useLocalSearchParams();

    // Parse params
    const name = params.name as string;
    const cook_time = params.cook_time as string;
    const ingredients = JSON.parse(params.recipe_ingredients as string || '[]');
    const instructions = JSON.parse(params.instructions as string || '[]');
    const day = params.day as string;
    const type = params.meal_type as string;

    const [checkedItems, setCheckedItems] = useState<Record<number, boolean>>({});

    const toggleItem = (index: number) => {
        setCheckedItems(prev => ({
            ...prev,
            [index]: !prev[index]
        }));
    };

    return (
        <SafeAreaView style={styles.container}>
            <Stack.Screen options={{
                title: name || 'Recipe Details',
                headerShown: true,
                headerTransparent: false,
                headerShadowVisible: false,
                headerStyle: { backgroundColor: '#F9F9F9' },
            }} />

            <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
                <View style={styles.headerSection}>
                    <View style={styles.badgeRow}>
                        <View style={styles.dayBadge}>
                            <Text style={styles.badgeText}>{day}</Text>
                        </View>
                        <View style={styles.typeBadge}>
                            <Text style={styles.badgeText}>{type}</Text>
                        </View>
                    </View>
                    <Text style={styles.title}>{name}</Text>
                    <View style={styles.metaRow}>
                        <Ionicons name="time-outline" size={16} color="#6B7280" />
                        <Text style={styles.metaText}>{cook_time}</Text>
                    </View>
                </View>

                <View style={styles.section}>
                    <Text style={styles.sectionTitle}>Ingredients</Text>
                    <View style={styles.card}>
                        {ingredients.map((item: { name: string, qty: number, unit: string, price?: number }, index: number) => (
                            <TouchableOpacity
                                key={index}
                                style={styles.checkItem}
                                onPress={() => toggleItem(index)}
                            >
                                <Ionicons
                                    name={checkedItems[index] ? "checkbox" : "square-outline"}
                                    size={20}
                                    color={checkedItems[index] ? "#10B981" : "#D1D5DB"}
                                />
                                <View style={{ flex: 1, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <View style={{ flex: 1, marginLeft: 12 }}>
                                        <Text style={[styles.itemText, checkedItems[index] && styles.checkedText, { marginLeft: 0 }]}>
                                            {item.name} ({item.qty} {item.unit})
                                        </Text>
                                    </View>
                                    {item.price !== undefined && item.price > 0 && (
                                        <Text style={[styles.priceText, checkedItems[index] && styles.checkedText]}>
                                            ${item.price.toFixed(2)}
                                        </Text>
                                    )}
                                </View>
                            </TouchableOpacity>
                        ))}
                    </View>
                </View>

                <View style={styles.section}>
                    <Text style={styles.sectionTitle}>Instructions</Text>
                    {instructions.map((step: string, index: number) => (
                        <View key={index} style={styles.instructionCard}>
                            <View style={styles.stepNumber}>
                                <Text style={styles.stepNumberText}>{index + 1}</Text>
                            </View>
                            <Text style={styles.instructionText}>{step}</Text>
                        </View>
                    ))}
                </View>

                <TouchableOpacity
                    style={styles.backButton}
                    onPress={() => router.back()}
                >
                    <Text style={styles.backButtonText}>Back to Meal Plan</Text>
                </TouchableOpacity>
            </ScrollView>
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#FFF2E0',
    },
    scrollContent: {
        padding: 24,
        paddingBottom: 40,
    },
    headerSection: {
        marginBottom: 32,
    },
    badgeRow: {
        flexDirection: 'row',
        gap: 8,
        marginBottom: 12,
    },
    dayBadge: {
        backgroundColor: '#1A1A1A',
        paddingHorizontal: 10,
        paddingVertical: 4,
        borderRadius: 6,
    },
    typeBadge: {
        backgroundColor: '#6B7280',
        paddingHorizontal: 10,
        paddingVertical: 4,
        borderRadius: 6,
    },
    badgeText: {
        color: '#FFF',
        fontSize: 10,
        fontWeight: 'bold',
        textTransform: 'uppercase',
    },
    title: {
        fontSize: 28,
        fontWeight: '700',
        color: '#1A1A1A',
        fontFamily: 'Garamond-Bold',
        lineHeight: 34,
    },
    metaRow: {
        flexDirection: 'row',
        alignItems: 'center',
        marginTop: 12,
        gap: 6,
    },
    metaText: {
        fontSize: 14,
        color: '#6B7280',
    },
    section: {
        marginBottom: 32,
    },
    sectionTitle: {
        fontSize: 18,
        fontWeight: '700',
        color: '#1A1A1A',
        marginBottom: 16,
        fontFamily: 'Garamond-Bold',
    },
    card: {
        backgroundColor: '#FFFFFF',
        borderRadius: 16,
        padding: 16,
        borderWidth: 1,
        borderColor: '#1A1A1A',
        shadowColor: '#000',
        shadowOpacity: 0.05,
        shadowRadius: 10,
        shadowOffset: { width: 0, height: 4 },
        elevation: 2,
    },
    checkItem: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 10,
        borderBottomWidth: 1,
        borderBottomColor: '#F3F4F6',
    },
    itemText: {
        fontSize: 15,
        color: '#374151',
        marginLeft: 12,
        flex: 1,
    },
    checkedText: {
        textDecorationLine: 'line-through',
        color: '#9CA3AF',
    },
    priceText: {
        fontSize: 14,
        fontWeight: '600',
        color: Colors.textLight,
    },
    instructionCard: {
        backgroundColor: '#FFFFFF',
        borderRadius: 16,
        padding: 20,
        marginBottom: 12,
        flexDirection: 'row',
        borderWidth: 1,
        borderColor: '#1A1A1A',
        shadowColor: '#000',
        shadowOpacity: 0.05,
        shadowRadius: 10,
        shadowOffset: { width: 0, height: 4 },
        elevation: 2,
    },
    stepNumber: {
        width: 28,
        height: 28,
        borderRadius: 14,
        backgroundColor: '#1A1A1A',
        justifyContent: 'center',
        alignItems: 'center',
        marginRight: 16,
        marginTop: 2,
    },
    stepNumberText: {
        color: '#FFF',
        fontSize: 14,
        fontWeight: 'bold',
    },
    instructionText: {
        flex: 1,
        fontSize: 15,
        color: '#374151',
        lineHeight: 22,
    },
    backButton: {
        marginTop: 8,
        backgroundColor: '#FFFFFF',
        borderWidth: 1,
        borderColor: '#1A1A1A',
        borderRadius: 12,
        padding: 16,
        alignItems: 'center',
    },
    backButtonText: {
        color: '#1A1A1A',
        fontWeight: '600',
        fontSize: 15,
    },
});
