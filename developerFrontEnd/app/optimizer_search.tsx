import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, TextInput } from 'react-native';
import { Stack, useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import TopBanner from '@/components/TopBanner';
import LoadingGate from '@/components/LoadingGate';
import GradientButton from '@/components/GradientButton';
import Logo from '@/components/Logo';

// Brand & styling constants
const ACCENT_ORANGE = '#EA7000';
const BG_CREAM = '#FFF2E0';

// Mock list of ingredients for search suggestions
const MOCK_INGREDIENTS = [
  'Organic Apples',
  'Avocado (hass)',
  'Asparagus Bunch',
  'Almond Milk (Unsweetened)',
  'Whole Wheat Bread',
  '2% Milk (1 Gallon)',
  'Chicken Breast (Boneless)',
  'Greek Yogurt (Plain)',
  'Eggs (Large Brown)',
  'Fresh Spinach Bag',
  'Bananas',
  'Orange Juice',
  'Cheddar Cheese',
  'Tomato Pasta Sauce',
  'Brown Rice Bag'
];

export default function OptimizerSearchScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const [gateVisible, setGateVisible] = useState(true);
  const [ingredientQuery, setIngredientQuery] = useState('');
  const [ingredients, setIngredients] = useState<string[]>([
    'Organic Apples',
    '2% Milk (1 Gallon)',
    'Whole Wheat Bread'
  ]);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  // Filter suggestions dynamically
  useEffect(() => {
    const q = ingredientQuery.trim().toLowerCase();
    if (q.length < 1) {
      setSuggestions([]);
      return;
    }
    const filtered = MOCK_INGREDIENTS.filter(
      (item) => item.toLowerCase().includes(q) && !ingredients.includes(item)
    ).slice(0, 5); // Cap at 5 suggestions
    setSuggestions(filtered);
  }, [ingredientQuery, ingredients]);

  const addIngredient = (item: string) => {
    if (item.trim() && !ingredients.includes(item.trim())) {
      setIngredients([...ingredients, item.trim()]);
    }
    setIngredientQuery('');
    setSuggestions([]);
  };

  const removeIngredient = (index: number) => {
    setIngredients(ingredients.filter((_, i) => i !== index));
  };

  const handleGenerate = () => {
    router.push({
      pathname: '/optimizer_results',
      params: {
        location: params.location || '123 Main St',
        time: params.time || '3',
        selectedStores: params.selectedStores || '[]',
        strategy: params.strategy || 'Lowest Total Cost',
        ingredients: JSON.stringify(ingredients)
      }
    });
  };

  if (gateVisible) {
    return (
      <View style={{ flex: 1 }}>
        <Stack.Screen options={{ headerShown: false }} />
        <LoadingGate durationMs={4000} onDone={() => setGateVisible(false)} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: BG_CREAM }}>
      <Stack.Screen options={{ headerShown: false }} />
      <TopBanner title="Homepage" />

      <ScrollView contentContainerStyle={[styles.container, { paddingTop: 92 }]} showsVerticalScrollIndicator={false}>
        {/* Space above the logo */}
        <View style={{ height: 0 }} />

        {/* Header Logo Section */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.push('/')}>
            <Logo size={288} />
          </TouchableOpacity>
        </View>

        {/* Card Container */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Your Grocery List</Text>
          <Text style={styles.cardDescription}>
            Type or search to add items to your grocery list. We will calculate the cheapest store split and route.
          </Text>

          {/* Add Ingredient Input Section */}
          <View style={styles.section}>
            <Text style={styles.label}>Add Ingredient</Text>
            <View style={styles.inputRow}>
              <Ionicons name="search" size={18} color="#9CA3AF" />
              <TextInput
                placeholder="Search or type ingredient..."
                placeholderTextColor="#9CA3AF"
                style={styles.iconInput}
                value={ingredientQuery}
                onChangeText={setIngredientQuery}
                onSubmitEditing={() => addIngredient(ingredientQuery)}
              />
              {ingredientQuery.length > 0 && (
                <TouchableOpacity onPress={() => addIngredient(ingredientQuery)} style={styles.addButton}>
                  <Ionicons name="add-circle" size={24} color={ACCENT_ORANGE} />
                </TouchableOpacity>
              )}
            </View>

            {/* Suggestions Box */}
            {suggestions.length > 0 && (
              <View style={styles.suggestBox}>
                {suggestions.map((s) => (
                  <TouchableOpacity
                    key={s}
                    style={styles.suggestItem}
                    onPress={() => addIngredient(s)}
                  >
                    <Ionicons name="add" size={16} color="#9CA3AF" />
                    <Text style={styles.suggestText}>{s}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            )}
          </View>

          {/* Current List Section */}
          <View style={styles.section}>
            <Text style={styles.label}>Current Items ({ingredients.length})</Text>
            {ingredients.length === 0 ? (
              <View style={styles.emptyContainer}>
                <Ionicons name="cart-outline" size={24} color="#9CA3AF" />
                <Text style={styles.emptyText}>Your list is empty. Add some items above!</Text>
              </View>
            ) : (
              <View style={styles.listContainer}>
                {ingredients.map((item, idx) => (
                  <View key={idx} style={styles.listItem}>
                    <Text style={styles.listItemText}>{item}</Text>
                    <TouchableOpacity onPress={() => removeIngredient(idx)} style={styles.removeButton}>
                      <Ionicons name="trash-outline" size={18} color="#EF4444" />
                    </TouchableOpacity>
                  </View>
                ))}
              </View>
            )}
          </View>

          {/* Action Trigger */}
          <View style={{ marginTop: 12 }}>
            <GradientButton
              title="Find Best Route & Prices"
              onPress={handleGenerate}
            />
          </View>
        </View>
      </ScrollView>
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
  header: {
    alignItems: 'center',
    marginTop: -35,
    marginBottom: -35,
    ...Platform.select({
      web: {
        textAlign: 'center' as any,
      }
    })
  },
  pageTitle: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#1A1A1A',
    fontFamily: 'Fraunces-Bold',
    textAlign: 'center',
    marginBottom: 20,
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
  },
  cardTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#333333',
    fontFamily: 'Fraunces-Bold',
    marginBottom: 8,
  },
  cardDescription: {
    color: '#666666',
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 24,
  },
  section: {
    marginBottom: 20,
  },
  label: {
    fontWeight: 'bold',
    fontSize: 14,
    color: '#333333',
    marginBottom: 8,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F9FAFB',
    borderRadius: 12,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  iconInput: {
    flex: 1,
    paddingVertical: 12,
    paddingLeft: 8,
    fontSize: 16,
    color: '#1A1A1A',
  },
  addButton: {
    padding: 4,
  },
  suggestBox: {
    marginTop: 4,
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    overflow: 'hidden',
  },
  suggestHeader: {
    fontSize: 11,
    fontWeight: 'bold',
    color: '#9CA3AF',
    textTransform: 'uppercase',
    paddingHorizontal: 12,
    paddingTop: 10,
    paddingBottom: 4,
    backgroundColor: '#F9FAFB',
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#E5E7EB',
  },
  suggestItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#F0F0F0',
    gap: 8,
  },
  suggestText: {
    fontSize: 14,
    color: '#374151',
  },
  emptyContainer: {
    alignItems: 'center',
    paddingVertical: 20,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderRadius: 12,
    borderStyle: 'dashed',
  },
  emptyText: {
    color: '#9CA3AF',
    marginTop: 8,
    fontSize: 14,
  },
  listContainer: {
    gap: 8,
  },
  listItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#F9FAFB',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  listItemText: {
    fontSize: 15,
    color: '#1A1A1A',
    fontWeight: '500',
  },
  removeButton: {
    padding: 4,
  },
});
