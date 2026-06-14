import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity, Alert, useWindowDimensions, Platform } from 'react-native';
import { Stack, useRouter, useLocalSearchParams } from 'expo-router';
import { Colors } from '@/constants/theme';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { Feather, Ionicons } from '@expo/vector-icons';
import { exportLinedShoppingListPdf } from '@/services/pdfExport';
import { DownloadFab } from '@/components/DownloadFab';
import { generatePlan, ShoppingPlanResponse, MealPlanItem, ShoppingPlanRequest } from '@/services/api';
import ShoppingMap from '@/components/ShoppingMap';
import Logo from '@/components/Logo';
import BeigeLoadingDots from '@/components/BeigeLoadingDots';
import GroupedCart, { CartItem } from '@/components/GroupedCart';
import Route52SavingsFooter from '@/components/Route52SavingsFooter';
import { planStore } from '@/services/planStore';

export default function ResultsScreen() {
  const {
    budget, time, location,
    dietary_restrictions, cuisines, experiment, cook_time,
    days, meals_per_day, household_size, calories,
    fridge_items, health_issues,
    has_costco_card,
    savedIndex,
    shopping_mode
  } = useLocalSearchParams<{
    budget?: string, time?: string, location?: string,
    dietary_restrictions?: string, cuisines?: string, experiment?: string, cook_time?: string,
    days?: string, meals_per_day?: string, household_size?: string, calories?: string,
    fridge_items?: string, health_issues?: string,
    has_costco_card?: string,
    savedIndex?: string,
    shopping_mode?: string
  }>();

  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [plan, setPlan] = useState<ShoppingPlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dayIcons: Record<string, string> = {
    "Monday": "calendar",
    "Tuesday": "sun",
    "Wednesday": "coffee",
    "Thursday": "clock",
    "Friday": "smile",
    "Saturday": "shopping-bag",
    "Sunday": "home"
  };

  useEffect(() => {
    async function fetchPlan() {
      try {
        setLoading(true);

        // Check if we are loading a saved plan
        if (savedIndex !== undefined) {
          const idx = parseInt(Array.isArray(savedIndex) ? savedIndex[0] : savedIndex);
          const savedPlan = planStore.getPlanByIndex(idx);
          if (savedPlan) {
            setPlan(savedPlan);
            setLoading(false);
            return;
          } else {
            throw new Error("Saved plan not found");
          }
        }
        const costcoParam = Array.isArray(has_costco_card) ? has_costco_card[0] : has_costco_card;
        console.log('DEBUG: has_costco_card param value:', costcoParam);

        const requestParams: ShoppingPlanRequest = {
          location: Array.isArray(location) ? location[0] : (location || 'Indianapolis, IN'),
          budget: parseFloat(Array.isArray(budget) ? budget[0] : (budget || '150')),
          time: parseFloat(Array.isArray(time) ? time[0] : (time || '3')),
          calories: parseInt(Array.isArray(calories) ? calories[0] : (calories || '2000')),
          household_size: parseInt(Array.isArray(household_size) ? household_size[0] : (household_size || '1')),
          days: parseInt(Array.isArray(days) ? days[0] : (days || '7')),
          meals_per_day: parseInt(Array.isArray(meals_per_day) ? meals_per_day[0] : (meals_per_day || '3')),
          dietary_restrictions: Array.isArray(dietary_restrictions) ? dietary_restrictions[0] : (dietary_restrictions || ''),
          health_issues: Array.isArray(health_issues) ? health_issues[0] : (health_issues || ''),
          cuisines: Array.isArray(cuisines) ? cuisines[0] : (cuisines || ''),
          experiment: (Array.isArray(experiment) ? experiment[0] : experiment) === 'true',
          cook_time: Array.isArray(cook_time) ? cook_time[0] : (cook_time || '30-45 minutes'),
          fridge_items: Array.isArray(fridge_items) ? fridge_items[0] : (fridge_items || ''),
          has_costco_card: costcoParam === 'true',
          fake_data: true
        };

        console.log('DEBUG: Final request parameters:', requestParams);
        const data = await generatePlan(requestParams);
        console.log('DEBUG FRONTEND: Received plan data:', JSON.stringify(data, null, 2));
        console.log('DEBUG FRONTEND: Cheapest Store Name:', data.cheapest_single_store_name);

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
  }, [budget, time, location, dietary_restrictions, cuisines, experiment, cook_time, days, meals_per_day, household_size, calories, savedIndex, has_costco_card, fridge_items, health_issues]);

  const handleSave = () => {
    if (plan) {
      const success = planStore.savePlan(plan);
      if (success) {
        if (Platform.OS === 'web') {
          alert("Meal plan saved!");
          router.navigate('/');
        } else {
          Alert.alert("Success", "Meal plan saved!", [
            { text: "OK", onPress: () => router.navigate('/') }
          ]);
        }
      } else {
        Alert.alert("Limit Reached", "You can only save up to 5 meal plans. Please discard an old one first.");
      }
    }
  };

  const handleDiscard = () => {
    router.navigate('/');
  };

  const handleViewRecipe = (meal: MealPlanItem) => {
    router.push({
      pathname: '/recipe_details',
      params: {
        name: meal.name,
        cook_time: meal.cook_time,
        recipe_ingredients: JSON.stringify(meal.ingredients),
        instructions: JSON.stringify(meal.instructions),
        day: meal.day,
        meal_type: meal.meal_type
      }
    });
  };

  const handleDownloadPdf = async () => {
    if (!plan || !plan.shopping_list) return;

    try {
      const stores = plan.shopping_list.map((s) => ({
        storeName: s.store,
        storeAddress: s.address,
        mapsUrl: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(s.address)}`,
        items: s.items.map((it) => {
          const name = it.name.replace(/\s*\(x\d+(\.\d+)?\)\s*/g, '').trim();
          const nameLower = name.toLowerCase();
          let category: any = 'Other';
          if (nameLower.includes('tomato') || nameLower.includes('onion') || nameLower.includes('potato') || nameLower.includes('carrot') || nameLower.includes('pepper') || nameLower.includes('apple') || nameLower.includes('banana')) category = 'Produce';
          else if (nameLower.includes('chicken') || nameLower.includes('beef') || nameLower.includes('meat') || nameLower.includes('pork')) category = 'Meat';
          else if (nameLower.includes('milk') || nameLower.includes('cheese') || nameLower.includes('yogurt') || nameLower.includes('egg')) category = 'Dairy';
          else if (nameLower.includes('frozen') || nameLower.includes('ice cream')) category = 'Frozen';
          else if (nameLower.includes('rice') || nameLower.includes('pasta') || nameLower.includes('bread') || nameLower.includes('oil') || nameLower.includes('salt') || nameLower.includes('oat')) category = 'Pantry';

          return {
            name,
            qty: it.qty,
            category
          };
        }),
      }));

      await exportLinedShoppingListPdf({
        brandName: "",
        stores,
      });
    } catch (error) {
      console.error("PDF Export Error:", error);
      Alert.alert("Export Failed", "There was an error generating your shopping list PDF.");
    }
  };

  const ListFooter = () => (
    <View style={styles.footerButtons}>
      {savedIndex === undefined ? (
        <>
          <TouchableOpacity
            style={[styles.actionButton, styles.saveButton]}
            onPress={handleSave}
          >
            <Text style={styles.actionButtonText}>Save Meal Plan</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.actionButton, styles.discardButton]}
            onPress={handleDiscard}
          >
            <Text style={[styles.actionButtonText, { color: Colors.text }]}>Discard</Text>
          </TouchableOpacity>
        </>
      ) : (
        <TouchableOpacity
          style={styles.backButton}
          onPress={() => router.navigate('/')}
        >
          <Text style={styles.backButtonText}>Back to Home</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  const { width: windowWidth } = useWindowDimensions();
  const PAGE_PADDING = 24; // Padded via contentContainerStyle in the outer FlatList
  const GAP = 16;
  const availableWidth = windowWidth - (PAGE_PADDING * 2);

  // A reasonable min-width for cards containing recipe details
  const minCardWidth = windowWidth > 1200 ? 400 : windowWidth > 900 ? 350 : windowWidth > 500 ? 280 : availableWidth;

  let columns = Math.floor(availableWidth / (minCardWidth + (availableWidth > minCardWidth ? GAP : 0)));
  columns = Math.max(1, Math.min(columns, 7)); // Min 1, Max 7 (number of days)

  const cardWidth = columns === 1 ? availableWidth : (availableWidth - (GAP * (columns - 1))) / columns;

  const renderMealCard = ({ item }: { item: { day: string, meals: MealPlanItem[] } }) => {
    const getMealIconInfo = (type: string) => {
      const t = type.toLowerCase();
      if (t.includes('breakfast')) return { name: 'sunrise', color: '#B45309' }; // Amber/Sun color
      if (t.includes('lunch')) return { name: 'coffee', color: '#2563EB' }; // Blue
      return { name: 'moon', color: '#4F46E5' }; // Indigo
    };

    return (
      <View style={[styles.mealCard, { width: cardWidth }]}>
        <View style={styles.mealCardHeader}>
          <View style={styles.dayIconCircle}>
            <Feather name={dayIcons[item.day] as any || 'calendar'} size={18} color={Colors.primary} />
          </View>
          <View>
            <Text style={styles.mealDay}>{item.day}</Text>
            <Text style={styles.mealCountSmall}>{item.meals.length} meals</Text>
          </View>
        </View>
        <View style={styles.mealDivider} />
        {item.meals.map((meal, idx) => {
          const iconInfo = getMealIconInfo(meal.meal_type);
          return (
            <View key={idx} style={styles.mealRow}>
              <View style={styles.mealIconWrapperSmall}>
                <Feather name={iconInfo.name as any} size={14} color={iconInfo.color} />
              </View>
              <View style={styles.mealInfo}>
                <Text style={styles.mealTypeSmall}>{meal.meal_type}</Text>
                <Text style={styles.mealRecipeSmall} numberOfLines={1}>{meal.name}</Text>
                <View style={styles.mealFooterSmall}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1 }}>
                    <IconSymbol name="clock.fill" size={10} color={Colors.textLight} />
                    <Text style={styles.mealTimeSmall}>{meal.cook_time}</Text>
                  </View>
                  <TouchableOpacity onPress={() => handleViewRecipe(meal)}>
                    <Text style={styles.detailsLink}>Details →</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>
          );
        })}
      </View>
    );
  };

  const renderStoreCard = ({ item, index }: { item: ShoppingPlanResponse['shopping_list'][0], index: number }) => {
    const storeHasCoupon = item.items.some((it) => !!it.coupon);
    const storeTotal = item.items.reduce((sum, prod) => sum + prod.price, 0);

    // Niche requirement: alternate comparison stores so they aren't all Whole Foods
    const comparisonStores = ["Whole Foods", "Trader Joe's", "Wegmans"];
    const targetComparison = comparisonStores[index % comparisonStores.length];

    // Higher-end stores usually cost more; use different multipliers for variety
    const multipliers: Record<string, number> = {
      "Whole Foods": 1.35,
      "Trader Joe's": 1.22,
      "Wegmans": 1.28
    };
    const multiplier = multipliers[targetComparison] || 1.3;

    const savings = (storeTotal * multiplier) - storeTotal;
    const showSavings = savings >= 1.0;

    return (
      <View style={styles.storeCard}>
        <View style={styles.storeHeader}>
          <View style={[styles.storeIcon, { backgroundColor: Colors.primary + '20' }]}>
            <Text style={[styles.storeInitial, { color: Colors.primary }]}>{item.store?.[0] || '?'}</Text>
          </View>
          <View style={styles.storeInfo}>
            <View style={styles.storeNameRow}>
              <Text style={styles.storeName}>{item.store}</Text>
              {storeHasCoupon && (
                <View style={styles.couponBadge}>
                  <Ionicons name="pricetag" size={11} color="#166534" />
                  <Text style={styles.couponBadgeText}>Coupon</Text>
                </View>
              )}
            </View>
            <Text style={styles.storeAddress}>{item.address}</Text>
          </View>
          <View style={styles.storeMeta}>
            {storeTotal > 0 && <Text style={styles.storeCost}>${storeTotal.toFixed(2)}</Text>}
            <Text style={styles.storeItems}>{item.items.length} items</Text>
          </View>
        </View>

        <View style={styles.divider} />

        {/* Use the new GroupedCart component instead of manual itemList mapping */}
        <GroupedCart
          items={item.items.map((it, iIdx) => {
            // Basic category inference
            const rawName = it.name || '';
            // Scrub any (x1.0) or similar baked-in strings
            const name = rawName.replace(/\s*\(x\d+(\.\d+)?\)\s*/g, '').trim();
            const qty = it.qty || 1;

            let category: CartItem['category'] = 'Other';
            const nameLower = name.toLowerCase();
            if (nameLower.includes('tomato') || nameLower.includes('onion') || nameLower.includes('potato') || nameLower.includes('carrot') || nameLower.includes('pepper') || nameLower.includes('apple') || nameLower.includes('banana')) category = 'Produce';
            else if (nameLower.includes('chicken') || nameLower.includes('beef') || nameLower.includes('meat') || nameLower.includes('pork')) category = 'Meat';
            else if (nameLower.includes('milk') || nameLower.includes('cheese') || nameLower.includes('yogurt') || nameLower.includes('egg')) category = 'Dairy';
            else if (nameLower.includes('frozen') || nameLower.includes('ice cream')) category = 'Frozen';
            else if (nameLower.includes('rice') || nameLower.includes('pasta') || nameLower.includes('bread') || nameLower.includes('oil') || nameLower.includes('salt') || nameLower.includes('oat')) category = 'Pantry';

            // Use real coupon data from backend; compute discount fraction from savings
            const hasCoupon = !!it.coupon;
            const couponDiscount = (hasCoupon && it.coupon.savings && it.price > 0)
              ? it.coupon.savings / (it.original_price ?? it.price)
              : undefined;

            return {
              id: `${index}-${iIdx}`,
              name,
              qty,
              price: it.price,
              category,
              hasCoupon,
              couponDiscount,
              onUseCoupon: () => router.push('/barcode')
            };
          })}
          cardStyle={styles.groupedCartContainer}
        />

        {/* Store Action Button based on shopping mode */}
        {shopping_mode === 'order_online' && (
          <View style={styles.storeActionContainer}>
            <TouchableOpacity style={styles.storeActionButton}>
              <Text style={styles.storeActionButtonText}>Order</Text>
            </TouchableOpacity>
          </View>
        )}
        {shopping_mode === 'delivery' && (
          <View style={styles.storeActionContainer}>
            <TouchableOpacity style={styles.storeActionButton}>
              <Text style={styles.storeActionButtonText}>Start Delivery</Text>
            </TouchableOpacity>
          </View>
        )}

      </View>
    );
  };

  if (loading) {
    return (
      <View style={[styles.container, styles.center, { backgroundColor: '#F9F9F9' }]}>
        <Stack.Screen options={{ headerShown: false }} />
        <Logo size={180} />
        <View style={{ height: 24 }} />
        <View style={styles.titleRow}>
          <Text style={styles.loadingText}>Optimizing your shopping trip</Text>
          <BeigeLoadingDots />
        </View>
        <Text style={styles.loadingSub}>Checking prices & locations...</Text>
      </View>
    );
  }

  if (error || !plan) {
    return (
      <View style={[styles.container, styles.center, { padding: 20, backgroundColor: '#F9F9F9' }]}>
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

        <TouchableOpacity style={styles.backButton} onPress={() => router.replace('/')}>
          <Text style={styles.backButtonText}>Go Back & Adjust</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Stack.Screen
        options={{
          headerShown: false,
        }}
      />

      <View style={styles.brandHeader}>
        <Logo size={84} />
      </View>

      <FlatList
        data={plan.shopping_list}
        keyExtractor={(item) => item.store}
        renderItem={({ item, index }) => renderStoreCard({ item, index })}
        ListHeaderComponent={
          <View>
            <View style={styles.summaryCard}>
              <View style={styles.summaryItem}>
                <Text style={styles.summaryLabel}>Total Cost</Text>
                <Text style={styles.summaryValue}>{plan.total_cost > 0 ? `$${plan.total_cost.toFixed(2)}` : 'N/A'}</Text>
              </View>
              <View style={styles.verticalLine} />
              <View style={styles.summaryItem}>
                <Text style={styles.summaryLabel}>Total Time</Text>
                <Text style={styles.summaryValue}>{Math.round(plan.total_time_minutes)} min</Text>
              </View>
            </View>

            {shopping_mode && (
              <View style={styles.shoppingModeContainer}>
                <Text style={styles.shoppingModeLabel}>
                  {shopping_mode === 'order_online' && '🛒 Order Online (Pick Up)'}
                  {shopping_mode === 'delivery' && '🚗 Delivery'}
                  {shopping_mode === 'shop_in_person' && '🏪 Shop In Person'}
                </Text>
              </View>
            )}

            {plan.cheapest_single_store_cost > 0 && (
              <View style={styles.cheapestSection}>
                <View style={styles.cheapestIconBadge}>
                  <Ionicons name="pricetag" size={14} color="#ee7422" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cheapestText}>
                    Cheapest single store is <Text style={styles.cheapestHighlight}>{plan.cheapest_single_store_name || 'MISSING NAME'}</Text> for <Text style={styles.cheapestHighlight}>${(plan.cheapest_single_store_cost * 1.35).toFixed(2)}</Text>
                  </Text>
                  {/* FORCED DEBUG OVERLAY */}
                  <Text style={{ fontSize: 8, color: '#999', marginTop: 2 }}>
                    Raw Name: "{String(plan.cheapest_single_store_name)}" | Cost: {plan.cheapest_single_store_cost}
                  </Text>
                </View>
              </View>
            )}

            <Text style={styles.sectionTitle}>Your Weekly Menu</Text>
            <View style={styles.mealGridContainer}>
              <FlatList
                scrollEnabled={false}
                key={columns}
                numColumns={columns}
                columnWrapperStyle={columns > 1 ? { gap: GAP } : undefined}
                data={Object.values(plan.meal_plan.reduce((acc, meal) => {
                  const day = meal.day;
                  if (!acc[day]) acc[day] = { day, meals: [] };
                  acc[day].meals.push(meal);
                  return acc;
                }, {} as Record<string, { day: string, meals: MealPlanItem[] }>))
                  .sort((a, b) => {
                    const dayOrder = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
                    return dayOrder.indexOf(a.day) - dayOrder.indexOf(b.day);
                  })
                }
                keyExtractor={(item) => item.day}
                renderItem={renderMealCard}
                contentContainerStyle={styles.mealListContainer}
              />
            </View>

            <Text style={styles.sectionTitle}>Shopping Route</Text>
            <View style={styles.mapContainer}>
              <ShoppingMap
                userLocation={plan.user_location}
                shoppingList={plan.shopping_list}
              />
            </View>
            <Text style={{ marginLeft: 4, marginBottom: 24, color: Colors.textLight }}>
              Route: {plan.route.join(' → ')}
            </Text>

            {plan.at_home_ingredients && plan.at_home_ingredients.length > 0 && (
              <View style={{ marginBottom: 24 }}>
                <Text style={styles.sectionTitle}>Used from Home</Text>
                <View style={styles.homeCard}>
                  {plan.at_home_ingredients.map((item, idx) => (
                    <View key={idx} style={styles.homeItemRow}>
                      <View style={styles.homeBullet} />
                      <Text style={styles.homeItemText}>{item.name.charAt(0).toUpperCase() + item.name.slice(1)} ({item.qty} {item.unit})</Text>
                      <View style={styles.homeTag}>
                        <Text style={styles.homeTagText}>AT HOME</Text>
                      </View>
                    </View>
                  ))}
                </View>
              </View>
            )}

            <Text style={styles.sectionTitle}>Shopping List</Text>
          </View>
        }
        ListFooterComponent={ListFooter}
        contentContainerStyle={{ padding: 24, paddingBottom: 40 }}
        showsVerticalScrollIndicator={false}
      />
      <DownloadFab label="Download list" onPress={handleDownloadPdf} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F9F9F9' },
  center: { alignItems: 'center', justifyContent: 'center' },

  brandHeader: {
    paddingTop: 60,
    paddingBottom: 10,
    alignItems: 'center',
    backgroundColor: '#F9F9F9',
  },
  brandTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#1A1A1A',
    fontFamily: 'Garamond-Bold',
    marginTop: 8,
  },

  loadingText: { fontSize: 40, fontWeight: '700', color: '#1A1A1A', fontFamily: 'Garamond-Bold' },
  loadingSub: { fontSize: 24, color: '#6B7280', marginTop: 12 },

  titleRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "center",
    flexWrap: "wrap",
    gap: 8,
  },

  mapContainer: {
    height: 300,
    marginHorizontal: 0,
    marginBottom: 20,
    borderRadius: 24,
    overflow: 'hidden',
    borderWidth: 1.5,
    borderColor: '#1A1A1A',
    backgroundColor: Colors.card,
  },

  summaryCard: {
    flexDirection: 'row',
    backgroundColor: Colors.card,
    marginBottom: 24,
    padding: 20,
    borderRadius: 16,
    justifyContent: 'space-between',
    borderWidth: 1.5,
    borderColor: '#1A1A1A',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 10,
    elevation: 3,
  },
  summaryItem: { alignItems: 'center', flex: 1, justifyContent: 'center' },
  summaryLabel: { fontSize: 12, color: Colors.textLight, textTransform: 'uppercase', marginBottom: 2, fontWeight: '600' },
  summaryValue: { fontSize: 20, fontWeight: 'bold', color: Colors.text },
  verticalLine: { width: 1, backgroundColor: Colors.border, marginHorizontal: 10 },

  cheapestSection: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    padding: 12,
    borderRadius: 12,
    marginBottom: 24,
    borderWidth: 1,
    borderColor: '#1A1A1A',
  },
  cheapestIconBadge: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#F9F9F9',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 10,
  },
  cheapestText: {
    fontSize: 13,
    color: '#1A1A1A',
    flex: 1,
  },
  cheapestHighlight: {
    fontWeight: '700',
    color: '#ee7422',
  },

  mealGridContainer: {
    width: '100%',
    marginBottom: 24,
  },
  mealListContainer: {
    paddingBottom: 8,
  },
  mealCard: {
    backgroundColor: Colors.card,
    borderRadius: 20,
    padding: 16,
    borderWidth: 1,
    borderColor: '#1A1A1A',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 3,
  },
  mealCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  dayIconCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#F0F0F0',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  mealDay: {
    fontSize: 15,
    fontWeight: '700',
    color: Colors.text,
    textTransform: 'uppercase',
  },
  mealCountSmall: {
    fontSize: 11,
    color: Colors.textLight,
  },
  mealDivider: {
    height: 1,
    backgroundColor: Colors.border,
    marginBottom: 16,
  },
  mealRow: {
    flexDirection: 'row',
    marginBottom: 12,
    alignItems: 'flex-start',
  },
  mealIconWrapperSmall: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: '#F0F0F0',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 10,
  },
  mealInfo: {
    flex: 1,
  },
  mealTypeSmall: {
    fontSize: 10,
    fontWeight: '600',
    color: Colors.textLight,
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  mealRecipeSmall: {
    fontSize: 13,
    fontWeight: 'bold',
    color: Colors.text,
    marginBottom: 4,
  },
  mealFooterSmall: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  detailsLink: {
    fontSize: 11,
    fontWeight: '700',
    color: Colors.primary,
  },
  mealTimeSmall: {
    fontSize: 10,
    color: Colors.textLight,
    marginLeft: 4,
  },

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
    fontSize: 18,
    fontWeight: 'bold',
    color: Colors.text,
    marginBottom: 12,
    marginTop: 8,
  },

  homeCard: {
    backgroundColor: '#F9F9F9',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1.5,
    borderColor: '#1A1A1A',
    marginBottom: 12,
  },
  homeItemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  homeBullet: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#15803D',
    marginRight: 10,
  },
  homeItemText: {
    flex: 1,
    fontSize: 14,
    color: '#166534',
    fontWeight: '500',
  },
  emptyText: {
    color: '#9CA3AF',
    fontSize: 16,
    textAlign: 'center',
  },
  homeTag: {
    backgroundColor: '#DCFCE7',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
  },
  homeTagText: {
    fontSize: 10,
    color: '#15803D',
    fontWeight: 'bold',
  },
  loaderText: {
    marginTop: 12,
    color: '#64748B',
    fontSize: 14,
  },

  storeCard: {
    backgroundColor: Colors.card,
    borderRadius: 16,
    marginBottom: 20,
    overflow: 'visible',
    borderWidth: 1.5,
    borderColor: '#1A1A1A',
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
  storeNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  storeName: { fontSize: 16, fontWeight: 'bold', color: Colors.text },
  couponBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#DCFCE7',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  couponBadgeText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#166534',
  },
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

  groupedCartContainer: {
    margin: 16,
    borderWidth: 0,
    shadowOpacity: 0,
    elevation: 0,
  },

  backButton: {
    backgroundColor: Colors.text, padding: 16, borderRadius: 12,
    alignItems: 'center', marginTop: 10
  },
  backButtonText: { color: '#fff', fontWeight: 'bold', fontSize: 16 },

  footerButtons: {
    gap: 12,
    marginTop: 10,
  },
  actionButton: {
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveButton: {
    backgroundColor: '#ee7422',
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

  shoppingModeContainer: {
    backgroundColor: '#FFF5E6',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    marginBottom: 24,
    borderWidth: 1,
    borderColor: '#ee7422',
    alignItems: 'center',
  },
  shoppingModeLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#ee7422',
  },

  storeActionContainer: {
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  storeActionButton: {
    backgroundColor: '#ee7422',
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  storeActionButtonText: {
    color: '#FFF',
    fontWeight: '700',
    fontSize: 15,
  },
});
