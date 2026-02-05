import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity, Alert } from 'react-native';
import { Stack, useRouter, useLocalSearchParams } from 'expo-router';
import { Colors } from '@/constants/theme';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { generatePlan, ShoppingPlanResponse } from '@/services/api';
import ShoppingMap from '@/components/ShoppingMap';

export default function ResultsScreen() {
  const router = useRouter();
  const {
    budget, time, location,
    dietary_restrictions, cuisines, experiment,
    cook_time, days, meals_per_day, calories
  } = useLocalSearchParams();
  const [loading, setLoading] = useState(true);
  const [plan, setPlan] = useState<ShoppingPlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchPlan() {
      try {
        setLoading(true);
        console.log('Fetching plan with:', { budget, time, location, dietary_restrictions, cuisines });

        const data = await generatePlan({
          location: Array.isArray(location) ? location[0] : (location || 'Indianapolis, IN'),
          budget: parseFloat(Array.isArray(budget) ? budget[0] : (budget || '150')),
          time: parseFloat(Array.isArray(time) ? time[0] : (time || '3')),
          calories: parseInt(Array.isArray(calories) ? calories[0] : (calories || '2000')),
          days: parseInt(Array.isArray(days) ? days[0] : (days || '7')),
          meals_per_day: parseInt(Array.isArray(meals_per_day) ? meals_per_day[0] : (meals_per_day || '3')),
          dietary_restrictions: Array.isArray(dietary_restrictions) ? dietary_restrictions[0] : (dietary_restrictions || ''),
          cuisines: Array.isArray(cuisines) ? cuisines[0] : (cuisines || ''),
          experiment: (Array.isArray(experiment) ? experiment[0] : experiment) === 'true',
          cook_time: Array.isArray(cook_time) ? cook_time[0] : (cook_time || '30-45 minutes'),
          fake_data: true
        });

        setPlan(data);
      } catch (err: any) {
        console.error("Plan Error", err);
        setError(err.message || "Failed to generate plan");
        Alert.alert("Error", "Could not generate plan. Is the backend running?");
      } finally {
        setLoading(false);
      }
    }

    fetchPlan();
  }, [budget, time, location, dietary_restrictions, cuisines, experiment, cook_time, days, meals_per_day, calories]);

  const ListFooter = () => (
    <TouchableOpacity
      style={styles.backButton}
      onPress={() => router.dismissAll()}
    >
      <Text style={styles.backButtonText}>Start New Plan</Text>
    </TouchableOpacity>
  );

  const renderStoreCard = ({ item }: { item: ShoppingPlanResponse['shopping_list'][0] }) => {
    const storeTotal = item.items.reduce((sum, prod) => sum + prod.price, 0);

    return (
      <View style={styles.storeCard}>
        <View style={styles.storeHeader}>
          <View style={[styles.storeIcon, { backgroundColor: Colors.primary + '20' }]}>
            <Text style={[styles.storeInitial, { color: Colors.primary }]}>{item.store?.[0] || '?'}</Text>
          </View>
          <View style={styles.storeInfo}>
            <Text style={styles.storeName}>{item.store}</Text>
            <Text style={styles.storeAddress}>{item.address}</Text>
          </View>
          <View style={styles.storeMeta}>
            <Text style={styles.storeCost}>${storeTotal.toFixed(2)}</Text>
            <Text style={styles.storeItems}>{item.items.length} items</Text>
          </View>
        </View>

        <View style={styles.divider} />

        <View style={styles.itemList}>
          {item.items.map((product, idx) => (
            <View key={idx} style={styles.itemRow}>
              <View style={styles.itemBullet} />
              <Text style={styles.itemName}>{product.name}</Text>
            </View>
          ))}
        </View>
      </View>
    );
  };

  if (loading) {
    return (
      <View style={[styles.container, styles.center]}>
        <Stack.Screen options={{ headerShown: false }} />
        <View style={styles.loadingCircle}>
          <IconSymbol name="basket.fill" size={50} color={Colors.primary} />
        </View>
        <Text style={styles.loadingText}>Optimizing your route...</Text>
        <Text style={styles.loadingSub}>Checking prices & locations...</Text>
      </View>
    );
  }

  if (error || !plan) {
    return (
      <View style={[styles.container, styles.center, { padding: 20 }]}>
        <Stack.Screen options={{ title: 'Error' }} />
        <IconSymbol name="exclamationmark.circle.fill" size={60} color={Colors.error} />
        <Text style={[styles.loadingText, { marginTop: 20 }]}>Planning Failed</Text>
        <Text style={[styles.loadingSub, { textAlign: 'center', marginBottom: 20 }]}>{error}</Text>

        {error?.includes("No stores found") && (
          <View style={styles.errorAdvice}>
            <Text style={styles.adviceTitle}>💡 Try these fixes:</Text>
            <Text style={styles.adviceItem}>• Increase your &quot;Shopping Time&quot; (e.g., to 60+ mins)</Text>
            <Text style={styles.adviceItem}>• Verify your location is correct</Text>
            <Text style={styles.adviceItem}>• Ensure you aren&apos;t in a very remote area</Text>
          </View>
        )}

        <TouchableOpacity style={styles.backButton} onPress={() => router.dismissAll()}>
          <Text style={styles.backButtonText}>Go Back & Adjust</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen
        options={{
          title: 'Optimal Plan',
          headerStyle: { backgroundColor: Colors.background },
          headerShadowVisible: false,
          headerTintColor: Colors.text,
        }}
      />

      <View style={styles.summaryCard}>
        <View style={styles.summaryItem}>
          <Text style={styles.summaryLabel}>Total Cost</Text>
          <Text style={styles.summaryValue}>${plan.total_cost.toFixed(2)}</Text>
        </View>
        <View style={styles.verticalLine} />
        <View style={styles.summaryItem}>
          <Text style={styles.summaryLabel}>Total Time</Text>
          <Text style={styles.summaryValue}>{plan.total_time_minutes} min</Text>
        </View>
      </View>

      <View style={styles.mapContainer}>
        <ShoppingMap
          userLocation={plan.user_location}
          shoppingList={plan.shopping_list}
        />
      </View>

      <FlatList
        data={plan.shopping_list}
        keyExtractor={(item) => item.store}
        renderItem={({ item }) => renderStoreCard({ item })}
        ListHeaderComponent={
          <View>
            <Text style={styles.sectionTitle}>Shopping Route</Text>
            <Text style={{ marginLeft: 4, marginBottom: 16, color: Colors.textLight }}>
              Route: {plan.route.join(' → ')}
            </Text>
          </View>
        }
        ListFooterComponent={ListFooter}
        contentContainerStyle={{ padding: 24, paddingBottom: 40 }}
        showsVerticalScrollIndicator={false}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  center: { alignItems: 'center', justifyContent: 'center' },

  loadingCircle: {
    width: 100, height: 100, borderRadius: 50,
    backgroundColor: Colors.card, elevation: 5,
    justifyContent: 'center', alignItems: 'center', marginBottom: 20
  },
  loadingText: { fontSize: 20, fontWeight: 'bold', color: Colors.text },
  loadingSub: { fontSize: 14, color: Colors.textLight, marginTop: 8 },

  mapContainer: {
    height: 250,
    marginHorizontal: 24,
    marginBottom: 20,
    borderRadius: 24,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.card,
  },

  summaryCard: {
    flexDirection: 'row',
    backgroundColor: Colors.card,
    margin: 24,
    marginTop: 10,
    padding: 20,
    borderRadius: 16,
    justifyContent: 'space-between',
    shadowColor: Colors.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 10,
    elevation: 3,
  },
  summaryItem: { alignItems: 'center', flex: 1 },
  summaryLabel: { fontSize: 12, color: Colors.textLight, textTransform: 'uppercase', marginBottom: 4, fontWeight: '600' },
  summaryValue: { fontSize: 18, fontWeight: 'bold', color: Colors.text },
  verticalLine: { width: 1, backgroundColor: Colors.border },

  errorAdvice: {
    backgroundColor: 'rgba(239, 68, 68, 0.05)',
    borderRadius: 12,
    padding: 16,
    marginBottom: 20,
    width: '100%',
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.1)',
  },
  adviceTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: Colors.error,
    marginBottom: 10,
  },
  adviceItem: {
    fontSize: 13,
    color: Colors.text,
    marginBottom: 6,
    lineHeight: 18,
  },

  sectionTitle: {
    fontSize: 18, fontWeight: 'bold', color: Colors.text, marginBottom: 8, marginLeft: 4
  },

  storeCard: {
    backgroundColor: Colors.card,
    borderRadius: 16,
    marginBottom: 20,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: Colors.border,
  },
  storeHeader: {
    flexDirection: 'row',
    padding: 16,
    alignItems: 'center',
  },
  storeIcon: {
    width: 48, height: 48, borderRadius: 12,
    justifyContent: 'center', alignItems: 'center',
    marginRight: 12,
  },
  storeInitial: { fontSize: 20, fontWeight: 'bold' },
  storeInfo: { flex: 1 },
  storeName: { fontSize: 16, fontWeight: 'bold', color: Colors.text },
  storeAddress: { fontSize: 12, color: Colors.textLight },
  storeMeta: { alignItems: 'flex-end' },
  storeCost: { fontSize: 16, fontWeight: 'bold', color: Colors.text },
  storeItems: { fontSize: 12, color: Colors.textLight },

  divider: { height: 1, backgroundColor: Colors.border, marginHorizontal: 16 },

  itemList: { padding: 16 },
  itemRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },
  itemBullet: { width: 6, height: 6, borderRadius: 3, backgroundColor: Colors.textLight, marginRight: 10 },
  itemName: { flex: 1, fontSize: 14, color: Colors.text },
  itemPrice: { fontSize: 14, fontWeight: '600', color: Colors.textLight },

  backButton: {
    backgroundColor: Colors.text, padding: 16, borderRadius: 12,
    alignItems: 'center', marginTop: 10
  },
  backButtonText: { color: '#fff', fontWeight: 'bold', fontSize: 16 }
});
