import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { useRouter, useNavigation } from 'expo-router';
import Logo from '@/components/Logo';
import GradientButton from '@/components/GradientButton';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { planStore, SavedPlan } from '@/services/planStore';

export default function HomeScreen() {
  const router = useRouter();
  const navigation = useNavigation();
  const [savedPlans, setSavedPlans] = useState<SavedPlan[]>([]);

  // Initial load and update whenever the screen comes into focus
  useEffect(() => {
    // Initial load
    setSavedPlans(planStore.getSavedPlans());

    const unsubscribe = navigation.addListener('focus', () => {
      setSavedPlans(planStore.getSavedPlans());
    });
    return unsubscribe;
  }, [navigation]);

  const handleStartNew = () => {
    // No warming here — we don't know which stores are relevant until an
    // address is entered. Warming used to fire both Walmart + Target
    // unconditionally at this point (no address, no idea if either is even
    // nearby), which just meant Render launched browsers for stores that
    // might not matter. See location.tsx: warming now only happens for
    // chains actually found near the address the user enters.
    router.push('/location');
  };

  // Address the plan by its stable id, not its position. With an index, deleting
  // any plan shifted every later one and the link opened the wrong plan.
  const handleViewSaved = (id: string) => {
    router.push({ pathname: '/results', params: { savedId: id } });
  };

  return (
    <ScrollView contentContainerStyle={styles.container} showsVerticalScrollIndicator={false}>
      <View style={styles.topBanner}>
        <Text style={styles.topBannerText}>Route 52: Smart Shopping, Simplified</Text>
      </View>
 
      <View style={styles.contentContainer}>
        <View style={styles.headerSection}>
        <Logo size={288} />
      </View>
 
        <View style={styles.actionSection}>
          <GradientButton
            title="Start New Meal Plan"
            onPress={handleStartNew}
          />
          <GradientButton
            title="Grocery Store Optimizer"
            onPress={() => router.push('/optimizer')}
          />
        </View>
 
        <View style={styles.savedSection}>
          <Text style={styles.sectionTitle}>Saved Meal Plans</Text>
          {savedPlans.length === 0 ? (
            <View style={styles.emptyCard}>
            <IconSymbol name="basket.fill" size={32} color="#9CA3AF" style={styles.emptyIcon} />
            <Text style={styles.emptyText}>No saved plans yet. Create one to get started!</Text>
          </View>
          ) : (
            savedPlans.map((entry, index) => (
              <View key={entry.id} style={styles.savedCardContainer}>
                <TouchableOpacity
                  style={styles.savedCard}
                  onPress={() => handleViewSaved(entry.id)}
                >
                  <IconSymbol name="cart.fill" size={24} color="#ee7422" style={styles.cartIcon} />
                  <View style={styles.savedCardContent}>
                    <Text style={styles.savedCardTitle}>Saved Plan {index + 1}</Text>
                    <Text style={styles.savedCardMeta}>
                      {entry.plan.meal_plan?.length ?? 0} meals • ${(entry.plan.total_cost ?? 0).toFixed(2)}
                    </Text>
                  </View>
                  <Text style={styles.viewLink}>View →</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.deleteButton}
                  onPress={() => {
                    planStore.deleteById(entry.id);
                    setSavedPlans(planStore.getSavedPlans());
                  }}
                >
                  <Text style={styles.deleteText}>✕</Text>
                </TouchableOpacity>
              </View>
            ))
          )}
          {planStore.isFull && (
            <Text style={styles.limitText}>
              Cap reached ({planStore.max}/{planStore.max}). Discard a plan to save a new one.
            </Text>
          )}
        </View>
 
        <View style={styles.footerSection}>
          <Text style={styles.footerText}>Your AI Grocery & Meal Assistant</Text>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    backgroundColor: '#FFF2E0',
  },
  contentContainer: {
    padding: 24,
    paddingTop: 4,
  },
  topBanner: {
    backgroundColor: '#b0db9d',
    paddingVertical: 24,
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
  },
  topBannerText: {
    color: '#000000',
    fontWeight: '700',
    fontSize: 24,
    letterSpacing: 0.5,
    fontFamily: 'WorkSans-Bold',
  },
  headerSection: {
    alignItems: 'center',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 16,
    color: '#6B7280',
    marginTop: 8,
    textAlign: 'center',
  },
  actionSection: {
    marginBottom: 20,
  },
  savedSection: {
    flex: 1,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#1A1A1A',
    marginBottom: 16,
    fontFamily: 'Fraunces-Bold',
  },
  emptyCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 18,
    padding: 30,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000000',
    shadowOpacity: 0.08,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 2,
  },
  emptyIcon: {
    marginRight: 12,
  },
  emptyText: {
    flexShrink: 1,
    color: '#9CA3AF',
    textAlign: 'center',
    fontSize: 14,
    fontFamily: 'WorkSans-Regular',
  },
  savedCardContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  savedCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 20,
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000000',
    shadowOpacity: 0.08,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
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
    color: '#1A1A1A',
    fontFamily: 'WorkSans-SemiBold',
  },
  savedCardMeta: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
    fontFamily: 'WorkSans-Regular',
  },
  viewLink: {
    color: '#1A1A1A',
    fontWeight: '700',
    fontSize: 14,
    fontFamily: 'WorkSans-Bold',
  },
  limitText: {
    fontSize: 12,
    color: '#9CA3AF',
    textAlign: 'center',
    marginTop: 8,
    fontStyle: 'italic',
    fontFamily: 'WorkSans-Regular',
  },
  footerSection: {
    marginTop: 32,
    alignItems: 'center',
    marginBottom: 20,
  },
  footerText: {
    fontSize: 14,
    color: '#000000',
    fontWeight: 'bold',
    textAlign: 'center',
    fontFamily: 'WorkSans-Bold',
  },
  cartIcon: {
    marginRight: 16,
  },
});