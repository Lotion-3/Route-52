import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, ActivityIndicator, Animated } from 'react-native';
import { Stack, useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import TopBanner from '@/components/TopBanner';
import Logo from '@/components/Logo';
import GradientButton from '@/components/GradientButton';
import ShoppingMap from '@/components/ShoppingMap';
import { DownloadFab } from '@/components/DownloadFab';
import { exportLinedShoppingListPdf } from '@/services/pdfExport';
import { notify, notifyThen } from '@/services/notify';
import { planStore } from '@/services/planStore';

// Brand & styling constants
const ACCENT_ORANGE = '#EA7000';
const BG_CREAM = '#FFF2E0';

// Mock store prices for items to simulate optimal split
const STORE_CATALOG: Record<string, { store: string; price: number }[]> = {
  'Organic Apples': [
    { store: 'Aldi', price: 3.49 },
    { store: 'Walmart', price: 3.99 },
    { store: 'Trader Joe\'s', price: 4.29 }
  ],
  'Avocado (hass)': [
    { store: 'Trader Joe\'s', price: 0.99 },
    { store: 'Aldi', price: 1.19 },
    { store: 'Walmart', price: 1.29 }
  ],
  'Asparagus Bunch': [
    { store: 'Aldi', price: 2.29 },
    { store: 'Walmart', price: 2.49 },
    { store: 'Kroger', price: 2.79 }
  ],
  'Almond Milk (Unsweetened)': [
    { store: 'Aldi', price: 1.99 },
    { store: 'Walmart', price: 2.19 },
    { store: 'Kroger', price: 2.39 }
  ],
  'Whole Wheat Bread': [
    { store: 'Aldi', price: 1.79 },
    { store: 'Walmart', price: 1.89 },
    { store: 'Kroger', price: 2.19 }
  ],
  '2% Milk (1 Gallon)': [
    { store: 'Walmart', price: 2.69 },
    { store: 'Aldi', price: 2.79 },
    { store: 'Kroger', price: 2.99 }
  ],
  'Chicken Breast (Boneless)': [
    { store: 'Aldi', price: 3.99 },
    { store: 'Walmart', price: 4.29 },
    { store: 'Kroger', price: 4.49 }
  ],
  'Greek Yogurt (Plain)': [
    { store: 'Aldi', price: 3.49 },
    { store: 'Trader Joe\'s', price: 3.79 },
    { store: 'Walmart', price: 3.89 }
  ],
  'Eggs (Large Brown)': [
    { store: 'Aldi', price: 2.49 },
    { store: 'Walmart', price: 2.69 },
    { store: 'Kroger', price: 2.99 }
  ],
  'Fresh Spinach Bag': [
    { store: 'Aldi', price: 1.49 },
    { store: 'Trader Joe\'s', price: 1.69 },
    { store: 'Walmart', price: 1.89 }
  ],
  'Bananas': [
    { store: 'Aldi', price: 0.49 },
    { store: 'Walmart', price: 0.52 },
    { store: 'Trader Joe\'s', price: 0.59 }
  ],
  'Orange Juice': [
    { store: 'Walmart', price: 3.29 },
    { store: 'Aldi', price: 3.49 },
    { store: 'Kroger', price: 3.79 }
  ],
  'Cheddar Cheese': [
    { store: 'Aldi', price: 2.19 },
    { store: 'Walmart', price: 2.29 },
    { store: 'Kroger', price: 2.49 }
  ],
  'Tomato Pasta Sauce': [
    { store: 'Aldi', price: 1.59 },
    { store: 'Walmart', price: 1.79 },
    { store: 'Trader Joe\'s', price: 1.99 }
  ],
  'Brown Rice Bag': [
    { store: 'Aldi', price: 1.29 },
    { store: 'Walmart', price: 1.39 },
    { store: 'Kroger', price: 1.49 }
  ]
};

export default function OptimizerResultsScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const [evalStage, setEvalStage] = useState(0);
  const [evaluating, setEvaluating] = useState(!params.savedId);
  const [percent, setPercent] = useState(0);
  const progressAnim = useRef(new Animated.Value(0)).current;
  const [loadedPlan, setLoadedPlan] = useState<any | null>(null);

  useEffect(() => {
    if (params.savedId) {
      const saved = planStore.getPlanById(params.savedId as string);
      if (saved) {
        setLoadedPlan(saved);
        setEvaluating(false);
      }
    }
  }, [params.savedId]);

  const rawIngredients = params.ingredients ? JSON.parse(params.ingredients as string) : [];
  const selectedStoresParam = params.selectedStores ? JSON.parse(params.selectedStores as string) : ['Aldi', 'Walmart'];
  const storesFilter = selectedStoresParam.length > 0 ? selectedStoresParam : ['Aldi', 'Walmart', 'Kroger', 'Trader Joe\'s'];

  // 4-stage evaluation animation
  useEffect(() => {
    if (!evaluating) return;
    
    // Animate the progress bar
    Animated.timing(progressAnim, {
      toValue: 1,
      duration: 3400,
      useNativeDriver: false,
    }).start();

    const listenerId = progressAnim.addListener(({ value }) => {
      setPercent(Math.round(value * 100));
    });

    const interval = setInterval(() => {
      setEvalStage((prev) => {
        if (prev >= 3) {
          clearInterval(interval);
          setTimeout(() => setEvaluating(false), 800);
          return 4;
        }
        return prev + 1;
      });
    }, 850);

    return () => {
      clearInterval(interval);
      progressAnim.removeListener(listenerId);
      progressAnim.stopAnimation();
    };
  }, [evaluating]);

  // Compute optimized shopping split based on input ingredients & selected stores
  const storeSplits: Record<string, { item: string; price: number }[]> = {};
  let totalCost = 0;
  let visitedStores: string[] = [];

  if (loadedPlan) {
    Object.assign(storeSplits, loadedPlan.meta.storeSplits);
    totalCost = loadedPlan.meta.totalCost;
    visitedStores = loadedPlan.meta.visitedStores;
  } else {
    rawIngredients.forEach((item: string) => {
      const catalog = STORE_CATALOG[item];
      let chosenStore = 'Walmart'; // default fallback
      let chosenPrice = 2.99;

      if (catalog) {
        // Find the cheapest store that is in the user's selected/preferred list
        const allowedPrices = catalog.filter((c) => storesFilter.includes(c.store));
        const bestDeal = allowedPrices.length > 0
          ? allowedPrices.reduce((prev, curr) => (prev.price < curr.price ? prev : curr))
          : catalog.reduce((prev, curr) => (prev.price < curr.price ? prev : curr)); // absolute cheapest fallback if none selected

        chosenStore = bestDeal.store;
        chosenPrice = bestDeal.price;
      } else {
        // Procedural mock price and store assignment for custom typed items
        const hash = item.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
        const storeIdx = hash % storesFilter.length;
        chosenStore = storesFilter[storeIdx];
        chosenPrice = parseFloat((1.99 + (hash % 10) * 0.75).toFixed(2));
      }

      if (!storeSplits[chosenStore]) {
        storeSplits[chosenStore] = [];
      }
      storeSplits[chosenStore].push({ item, price: chosenPrice });
      totalCost += chosenPrice;
    });
    visitedStores = Object.keys(storeSplits);
  }

  const USER_LOC = { lat: 37.7749, lng: -122.4194 };

  const MOCK_STORE_LOCATIONS: Record<string, { lat: number; lng: number; address: string }> = {
    'Aldi': { lat: 37.7801, lng: -122.4120, address: '801 Market St, San Francisco, CA' },
    'Walmart': { lat: 37.7690, lng: -122.4280, address: '1200 Folsom St, San Francisco, CA' },
    'Kroger': { lat: 37.7850, lng: -122.4300, address: '2200 Fillmore St, San Francisco, CA' },
    "Trader Joe's": { lat: 37.7700, lng: -122.4050, address: '555 9th St, San Francisco, CA' }
  };

  const mockShoppingList = visitedStores.map((store) => ({
    store,
    address: MOCK_STORE_LOCATIONS[store]?.address || 'Nearby Location',
    coordinates: {
      lat: MOCK_STORE_LOCATIONS[store]?.lat || 37.77,
      lng: MOCK_STORE_LOCATIONS[store]?.lng || -122.41
    }
  }));

  const handleSave = () => {
    const planToSave: any = {
      isOptimizer: true,
      total_cost: totalCost,
      total_time_minutes: visitedStores.length * 15 + 10,
      user_location: USER_LOC,
      route: ['Start', ...visitedStores, 'Home'],
      shopping_list: visitedStores.map((store) => ({
        store,
        address: MOCK_STORE_LOCATIONS[store]?.address || 'Nearby Location',
        coordinates: {
          lat: MOCK_STORE_LOCATIONS[store]?.lat || 37.77,
          lng: MOCK_STORE_LOCATIONS[store]?.lng || -122.41
        },
        items: storeSplits[store].map((itemObj) => ({
          name: itemObj.item,
          price: itemObj.price,
          qty: 1
        }))
      })),
      meta: {
        location: params.location,
        duration: params.duration,
        ingredients: params.ingredients,
        storeSplits: storeSplits,
        totalCost: totalCost,
        visitedStores: visitedStores
      }
    };

    const id = planStore.savePlan(planToSave);
    if (id) {
      notifyThen(
        'Saved',
        'Grocery list saved. Note: saved lists are kept for this session only.',
        () => router.navigate('/'),
      );
    } else {
      notify('Limit reached', `You can only save up to ${planStore.max} items. Discard a plan first.`);
    }
  };

  const handleDiscard = () => {
    router.navigate('/');
  };

  const handleDownloadPdf = async () => {
    try {
      const stores = visitedStores.map((store) => ({
        storeName: store,
        storeAddress: MOCK_STORE_LOCATIONS[store]?.address || 'Nearby Location',
        mapsUrl: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(MOCK_STORE_LOCATIONS[store]?.address || store)}`,
        items: storeSplits[store].map((itemObj) => ({
          name: itemObj.item,
          qty: 1,
          category: 'Other'
        })),
      }));

      await exportLinedShoppingListPdf({
        stores,
      });
    } catch (error) {
      console.error("PDF Export Error:", error);
    }
  };

  const EVAL_STAGES = [
    'Analyzing grocery list...',
    'Comparing local store pricing...',
    'Generating cheapest store split...',
    'Calculating optimal travel route...',
    'Almost ready...'
  ];

  if (evaluating) {
    return (
      <View style={styles.evalContainer}>
        <Stack.Screen options={{ headerShown: false }} />
        <View style={styles.evalContent}>
          <Logo size={200} />
          <Text style={styles.evalTitle}>Evaluating Route</Text>
          <Text style={styles.evalSub}>{EVAL_STAGES[Math.min(evalStage, 4)]}</Text>
          
          <View style={styles.barTrack}>
            <Animated.View style={[styles.barFillWrap, { width: progressAnim.interpolate({
              inputRange: [0, 1],
              outputRange: ['0%', '100%'],
            }) }]}>
              <LinearGradient
                colors={['#f7a14e', '#ee7422']}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 0 }}
                style={styles.barFill}
              />
            </Animated.View>
          </View>
          <Text style={styles.percent}>{percent}%</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: BG_CREAM }}>
      <Stack.Screen options={{ headerShown: false }} />
      <TopBanner title="Your Route" largeTitle={true} />

      <ScrollView contentContainerStyle={[styles.container, { paddingTop: 92 }]} showsVerticalScrollIndicator={false}>
        {/* Significant space between top card and green banner */}
        <View style={{ height: 40 }} />

        {/* Summary Card */}
        <View style={styles.summaryCard}>
          <View style={styles.summaryCol}>
            <Text style={styles.summaryLabel}>Total Cost</Text>
            <Text style={styles.summaryVal}>${totalCost.toFixed(2)}</Text>
          </View>
          <View style={styles.divider} />
          <View style={styles.summaryCol}>
            <Text style={styles.summaryLabel}>Stores Visited</Text>
            <Text style={styles.summaryVal}>{visitedStores.length}</Text>
          </View>
          <View style={styles.divider} />
          <View style={styles.summaryCol}>
            <Text style={styles.summaryLabel}>Travel Time</Text>
            <Text style={styles.summaryVal}>{visitedStores.length * 15 + 10} mins</Text>
          </View>
        </View>

        {/* Route Card */}
        <View style={styles.card}>
          <Text style={styles.sectionHeader}>Optimal Route</Text>
          <View style={styles.mapContainer}>
            <ShoppingMap
              userLocation={USER_LOC}
              shoppingList={mockShoppingList}
            />
          </View>
          <Text style={{ marginTop: 12, color: '#6B7280', fontSize: 13, fontFamily: 'WorkSans-Regular' }}>
            Route: Start → {visitedStores.join(' → ')} → Home
          </Text>
        </View>

        {/* Store Split Breakdown Card */}
        <View style={styles.card}>
          <Text style={styles.sectionHeader}>Cheapest Store Split</Text>
          {visitedStores.length === 0 ? (
            <Text style={styles.noItemsText}>No items to display.</Text>
          ) : (
            visitedStores.map((store) => (
              <View key={store} style={styles.storeBlock}>
                <View style={styles.storeHeader}>
                  <Text style={styles.storeName}>{store}</Text>
                  <View style={styles.priceContainer}>
                    <Text style={[styles.dollarSign, styles.storeSubtotalDollar]}>$</Text>
                    <Text style={styles.storeSubtotalNumber}>
                      {storeSplits[store].reduce((acc, curr) => acc + curr.price, 0).toFixed(2)}
                    </Text>
                  </View>
                </View>
                <View style={styles.itemsList}>
                  {storeSplits[store].map((itemObj, i) => (
                    <View key={i} style={styles.itemRow}>
                      <Text style={styles.itemName}>{itemObj.item}</Text>
                      <View style={styles.priceContainer}>
                        <Text style={[styles.dollarSign, styles.itemPriceDollar]}>$</Text>
                        <Text style={styles.itemPriceNumber}>
                          {itemObj.price.toFixed(2)}
                        </Text>
                      </View>
                    </View>
                  ))}
                </View>
              </View>
            ))
          )}
          {visitedStores.length > 0 && (
            <View style={styles.splitTotalTab}>
              <Text style={styles.splitTotalLabel}>Total</Text>
              <View style={styles.priceContainer}>
                <Text style={[styles.dollarSign, styles.splitTotalDollar]}>$</Text>
                <Text style={styles.splitTotalNumber}>{totalCost.toFixed(2)}</Text>
              </View>
            </View>
          )}
        </View>

        <View style={styles.footerButtons}>
          <TouchableOpacity
            style={[styles.actionButton, styles.saveButton]}
            onPress={handleSave}
          >
            <Text style={styles.actionButtonText}>Save List</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.actionButton, styles.discardButton]}
            onPress={handleDiscard}
          >
            <Text style={[styles.actionButtonText, { color: '#1A1A1A' }]}>Discard</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
      <DownloadFab label="Download list" onPress={handleDownloadPdf} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    backgroundColor: BG_CREAM,
    paddingHorizontal: 16,
    paddingVertical: 32,
  },
  pageTitle: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#1A1A1A',
    fontFamily: 'Fraunces-Bold',
    textAlign: 'center',
    marginTop: 40,
    marginBottom: 40,
  },
  evalContainer: {
    flex: 1,
    backgroundColor: BG_CREAM,
    justifyContent: 'center',
    alignItems: 'center',
  },
  evalContent: {
    alignItems: 'center',
    width: '100%',
    maxWidth: 400,
    padding: 24,
  },
  evalTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    fontFamily: 'Fraunces-Bold',
    color: '#1A1A1A',
    marginTop: -35,
  },
  evalSub: {
    fontSize: 15,
    color: '#6B7280',
    textAlign: 'center',
    marginTop: 6,
    marginBottom: 8,
    minHeight: 20,
    fontFamily: 'WorkSans-Regular',
  },
  summaryCard: {
    flexDirection: 'row',
    backgroundColor: '#FFFFFF',
    paddingVertical: 20,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    marginBottom: 20,
    maxWidth: 900,
    width: '100%',
    alignSelf: 'center',
  },
  summaryCol: {
    flex: 1,
    alignItems: 'center',
  },
  summaryLabel: {
    fontSize: 12,
    color: '#9CA3AF',
    textTransform: 'uppercase',
    fontWeight: '600',
    fontFamily: 'WorkSans-Regular',
  },
  summaryVal: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1A1A1A',
    marginTop: 4,
    fontFamily: 'WorkSans-Bold',
  },
  divider: {
    width: 1,
    backgroundColor: '#E5E7EB',
    height: '100%',
  },
  card: {
    backgroundColor: '#FFFFFF',
    padding: 24,
    borderRadius: 12,
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
    maxWidth: 900,
    alignSelf: 'center',
    width: '100%',
    marginBottom: 20,
  },
  sectionHeader: {
    fontSize: 18,
    fontWeight: 'bold',
    fontFamily: 'Fraunces-Bold',
    color: '#1A1A1A',
    marginBottom: 16,
  },
  routeContainer: {
    paddingLeft: 8,
  },
  routeNode: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
  },
  routeNodeText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#1A1A1A',
  },
  routeSubText: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 2,
  },
  routeLine: {
    width: 2,
    height: 24,
    backgroundColor: '#E5E7EB',
    marginLeft: 11,
    marginVertical: 4,
  },
  storeBlock: {
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 12,
    overflow: 'hidden',
  },
  storeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: '#F9FAFB',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  storeName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1A1A1A',
  },
  storeSubtotal: {
    fontSize: 16,
    fontWeight: 'bold',
    color: ACCENT_ORANGE,
  },
  priceContainer: {
    flexDirection: 'row',
    width: 60,
    justifyContent: 'flex-start',
  },
  dollarSign: {
    width: 14,
    fontFamily: 'WorkSans-Regular',
  },
  storeSubtotalDollar: {
    fontSize: 16,
    fontWeight: 'bold',
    color: ACCENT_ORANGE,
  },
  storeSubtotalNumber: {
    fontSize: 16,
    fontWeight: 'bold',
    color: ACCENT_ORANGE,
    fontFamily: 'WorkSans-Regular',
  },
  itemPriceDollar: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1A1A1A',
  },
  itemPriceNumber: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1A1A1A',
    fontFamily: 'WorkSans-Regular',
  },
  itemsList: {
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  itemRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#F0F0F0',
  },
  itemName: {
    fontSize: 14,
    color: '#374151',
    flex: 1,
    marginRight: 8,
  },
  noItemsText: {
    color: '#9CA3AF',
    fontStyle: 'italic',
    textAlign: 'center',
  },
  splitTotalTab: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#F3F4F6',
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 12,
    marginTop: 0,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  splitTotalLabel: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1A1A1A',
  },
  splitTotalDollar: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1A1A1A',
  },
  splitTotalNumber: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1A1A1A',
    fontFamily: 'WorkSans-Regular',
  },
  barTrack: {
    width: '100%',
    maxWidth: 320,
    height: 10,
    borderRadius: 999,
    backgroundColor: '#E5E7EB',
    overflow: 'hidden',
    marginTop: 4,
    marginBottom: 8,
  },
  barFillWrap: {
    height: '100%',
  },
  barFill: {
    flex: 1,
    borderRadius: 999,
  },
  percent: {
    fontSize: 14,
    fontWeight: '600',
    color: '#9CA3AF',
    fontFamily: 'WorkSans-Regular',
    marginBottom: 16,
  },
  mapContainer: {
    height: 300,
    marginHorizontal: 0,
    borderRadius: 16,
    overflow: 'hidden',
    borderWidth: 1.5,
    borderColor: '#1A1A1A',
    backgroundColor: '#FFFFFF',
  },
  footerButtons: {
    gap: 12,
    marginTop: 8,
    marginBottom: 24,
  },
  actionButton: {
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveButton: {
    backgroundColor: '#E8821E',
  },
  discardButton: {
    backgroundColor: 'transparent',
    borderWidth: 1.5,
    borderColor: '#1A1A1A',
  },
  actionButtonText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 16,
  },
});
