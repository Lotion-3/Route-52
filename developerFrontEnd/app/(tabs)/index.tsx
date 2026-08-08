import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform } from 'react-native';
import { useRouter, useNavigation } from 'expo-router';
import Logo from '@/components/Logo';
import GradientButton from '@/components/GradientButton';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { planStore, SavedPlan } from '@/services/planStore';

function ZigzagEdge({ color = '#b0db9d' }: { color?: string }) {
  if (Platform.OS !== 'web') return null;

  return React.createElement(
    'svg',
    {
      viewBox: '0 0 100 10',
      preserveAspectRatio: 'none',
      style: { width: '100%', height: '12px', display: 'block' },
    },
    React.createElement('polygon', {
      points: '0,0 5,10 10,0 15,10 20,0 25,10 30,0 35,10 40,0 45,10 50,0 55,10 60,0 65,10 70,0 75,10 80,0 85,10 90,0 95,10 100,0',
      fill: color,
    })
  );
}

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
    <View style={{ flex: 1, backgroundColor: '#FFF2E0' }}>
      <View style={{ position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10 }}>
        <View style={styles.topBanner}>
          {/* CSS background dot grid on Web */}
          {Platform.OS === 'web' && (
            <View
              style={{
                position: 'absolute',
                top: 0, left: 0, right: 0, bottom: 0,
                backgroundImage: 'radial-gradient(rgba(74, 122, 58, 0.08) 12%, transparent 13%)',
                backgroundSize: '16px 16px',
                backgroundPosition: '8px 8px',
              } as any}
              pointerEvents="none"
            />
          )}

          <View style={styles.bannerContentRow}>
            <View style={[styles.notch, { left: 16 }]} />
            <Text style={styles.topBannerText}>Route 52: Savings All Around</Text>
            <View style={[styles.notch, { right: 16 }]} />
          </View>

          {/* Perforation line */}
          <View style={[styles.perforationLine, Platform.OS === 'web' && {
            backgroundImage: 'linear-gradient(to right, #FFF8F0 65%, transparent 65%)',
            backgroundSize: '24px 2px',
            backgroundRepeat: 'repeat-x',
            borderStyle: 'none',
            borderWidth: 0,
            height: 2,
          } as any]} />
        </View>
        <ZigzagEdge />
      </View>

      <ScrollView contentContainerStyle={[styles.container, { paddingTop: 97 }]} showsVerticalScrollIndicator={false}>
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
              title="Grocery List Optimizer"
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
    </View>
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
    paddingVertical: 26,
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
    position: 'relative',
  },
  perforationLine: {
    position: 'absolute',
    bottom: 8,
    left: 0,
    right: 0,
    borderWidth: 1,
    borderColor: '#FFF8F0',
    borderStyle: 'dashed',
    height: 0,
  },
  bannerContentRow: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  notch: {
    position: 'absolute',
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: '#FFF2E0',
    zIndex: 5,
  },
  topBannerText: {
    color: '#000000',
    fontWeight: '700',
    fontSize: 28,
    letterSpacing: 0.5,
    fontFamily: 'Fraunces-Bold',
    zIndex: 2,
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
    marginBottom: 40,
    gap: 10,
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
    paddingVertical: 20,
    paddingHorizontal: 24,
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000000',
    shadowOpacity: 0.08,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 2,
    gap: 16,
  },
  emptyIcon: {},
  emptyText: {
    flex: 1,
    color: '#9CA3AF',
    textAlign: 'left',
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
    color: '#9CA3AF',
    textAlign: 'center',
    fontFamily: 'WorkSans-Regular',
  },
  cartIcon: {
    marginRight: 16,
  },
});