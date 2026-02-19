import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { useRouter, useNavigation } from 'expo-router';
import { Colors } from '@/constants/theme';
import Logo from '@/components/Logo';
import GradientButton from '@/components/GradientButton';
import { planStore } from '@/services/planStore';
import { ShoppingPlanResponse } from '@/services/api';

export default function HomeScreen() {
  const router = useRouter();
  const navigation = useNavigation();
  const [savedPlans, setSavedPlans] = useState<ShoppingPlanResponse[]>([]);

  // Update saved plans whenever the screen comes into focus
  useEffect(() => {
    const unsubscribe = navigation.addListener('focus', () => {
      setSavedPlans(planStore.getSavedPlans());
    });
    return unsubscribe;
  }, [navigation]);

  const handleStartNew = () => {
    router.push('/search');
  };

  const handleViewSaved = (index: number) => {
    router.push({
      pathname: '/results',
      params: { savedIndex: index.toString() }
    });
  };

  return (
    <ScrollView contentContainerStyle={styles.container} showsVerticalScrollIndicator={false}>
      <View style={styles.headerSection}>
        <Logo size={120} />
        <Text style={styles.title}>BasketBuddys</Text>
        <Text style={styles.subtitle}>Your AI Grocery & Meal Assistant</Text>
      </View>

      <View style={styles.actionSection}>
        <GradientButton
          title="Start New Meal Plan"
          onPress={handleStartNew}
        />
      </View>

      <View style={styles.savedSection}>
        <Text style={styles.sectionTitle}>Saved Meal Plans</Text>
        {savedPlans.length === 0 ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyText}>No saved plans yet. Create one to get started!</Text>
          </View>
        ) : (
          savedPlans.map((plan, index) => (
            <View key={index} style={styles.savedCardContainer}>
              <TouchableOpacity
                style={styles.savedCard}
                onPress={() => handleViewSaved(index)}
              >
                <View style={styles.savedCardContent}>
                  <Text style={styles.savedCardTitle}>Saved Meal {index + 1}</Text>
                  <Text style={styles.savedCardMeta}>
                    {plan.meal_plan.length} meals • ${plan.total_cost.toFixed(2)}
                  </Text>
                </View>
                <Text style={styles.viewLink}>View →</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.deleteButton}
                onPress={() => {
                  planStore.deletePlan(index);
                  setSavedPlans(planStore.getSavedPlans());
                }}
              >
                <Text style={styles.deleteText}>✕</Text>
              </TouchableOpacity>
            </View>
          ))
        )}
        {savedPlans.length >= 5 && (
          <Text style={styles.limitText}>Cap reached (5/5). Discard a plan to save a new one.</Text>
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    backgroundColor: '#F7F2EA',
    padding: 24,
    paddingTop: 80,
  },
  headerSection: {
    alignItems: 'center',
    marginBottom: 40,
  },
  title: {
    fontSize: 32,
    fontWeight: '700',
    color: '#1F2933',
    fontFamily: 'Garamond-Bold',
    marginTop: 16,
  },
  subtitle: {
    fontSize: 16,
    color: '#6B7280',
    marginTop: 8,
    textAlign: 'center',
  },
  actionSection: {
    marginBottom: 40,
  },
  savedSection: {
    flex: 1,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#1F2933',
    marginBottom: 16,
    fontFamily: 'Garamond-Bold',
  },
  emptyCard: {
    backgroundColor: '#FEFEFC',
    borderRadius: 18,
    padding: 30,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderStyle: 'dashed',
  },
  emptyText: {
    color: '#9CA3AF',
    textAlign: 'center',
    fontSize: 14,
  },
  savedCardContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  savedCard: {
    backgroundColor: '#FEFEFC',
    borderRadius: 16,
    padding: 20,
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  deleteButton: {
    marginLeft: 12,
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#FEE2E2',
    justifyContent: 'center',
    alignItems: 'center',
  },
  deleteText: {
    color: '#EF4444',
    fontSize: 14,
    fontWeight: 'bold',
  },
  savedCardContent: {
    flex: 1,
  },
  savedCardTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2933',
  },
  savedCardMeta: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
  },
  viewLink: {
    color: '#1F2933',
    fontWeight: '700',
    fontSize: 14,
  },
  limitText: {
    fontSize: 12,
    color: '#9CA3AF',
    textAlign: 'center',
    marginTop: 8,
    fontStyle: 'italic',
  }
});