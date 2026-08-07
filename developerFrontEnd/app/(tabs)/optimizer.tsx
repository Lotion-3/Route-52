import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

// Brand & styling constants
const ACCENT_ORANGE = '#EA7000'; // Matching orange from design
const BG_CREAM = '#FFF2E0';

type StrategyOption =
  | 'Lowest Total Cost (Split items across multiple stores)'
  | 'Single Store Speed (Fastest shopping trip)'
  | 'Aisle-by-Aisle Route (Sorted for minimal walk time inside store)';

export default function GroceryStoreOptimizerView() {
  const router = useRouter();
  const [selectedStores, setSelectedStores] = useState<string[]>([]);
  const [strategy, setStrategy] = useState<StrategyOption>('Lowest Total Cost (Split items across multiple stores)');
  const [showDropdown, setShowDropdown] = useState(false);

  const stores = ['Aldi', 'Kroger', "Trader Joe's", 'Walmart'];

  const strategies: StrategyOption[] = [
    'Lowest Total Cost (Split items across multiple stores)',
    'Single Store Speed (Fastest shopping trip)',
    'Aisle-by-Aisle Route (Sorted for minimal walk time inside store)'
  ];

  const toggleStore = (store: string) => {
    if (selectedStores.includes(store)) {
      setSelectedStores(selectedStores.filter((s) => s !== store));
    } else {
      setSelectedStores([...selectedStores, store]);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.container} showsVerticalScrollIndicator={false}>
      <Stack.Screen options={{ headerShown: false }} />

      {/* Header Logo Section */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.push('/')}>
          <Text style={styles.headerTitle}>ROUTE 52</Text>
        </TouchableOpacity>
        <Text style={styles.headerSub}>Your AI Grocery & Meal Assistant</Text>
      </View>

      {/* Main Container resembling the provided HTML card */}
      <View style={styles.card}>
        <View style={styles.cardHeaderRow}>
          <Text style={styles.cardTitle}>Grocery Store Optimizer</Text>
          <TouchableOpacity onPress={() => router.push('/')} style={styles.backButton}>
            <Ionicons name="close" size={24} color="#666" />
          </TouchableOpacity>
        </View>
        <Text style={styles.cardDescription}>
          Select your local stores and preferences to generate the fastest route and cheapest cart split.
        </Text>

        {/* Feature 1: Store Selection */}
        <View style={styles.section}>
          <Text style={styles.label}>Select Nearby Stores</Text>
          <View style={styles.storeRow}>
            {stores.map((store) => {
              const isSelected = selectedStores.includes(store);
              return (
                <TouchableOpacity
                  key={store}
                  onPress={() => toggleStore(store)}
                  style={[
                    styles.storeButton,
                    isSelected && styles.storeButtonSelected
                  ]}
                >
                  <Text style={[styles.storeButtonText, isSelected && styles.storeButtonTextSelected]}>
                    {isSelected ? '✓ ' : '+ '} {store}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>

        {/* Feature 2: Optimization Preference */}
        <View style={styles.section}>
          <Text style={styles.label}>Optimization Strategy</Text>
          <TouchableOpacity
            style={styles.dropdownSelector}
            onPress={() => setShowDropdown(!showDropdown)}
          >
            <Text style={styles.dropdownSelectorText} numberOfLines={1}>
              {strategy}
            </Text>
            <Ionicons name={showDropdown ? "chevron-up" : "chevron-down"} size={20} color="#666" />
          </TouchableOpacity>

          {showDropdown && (
            <View style={styles.dropdown}>
              {strategies.map((option) => (
                <TouchableOpacity
                  key={option}
                  style={[
                    styles.dropdownItem,
                    strategy === option && styles.dropdownItemSelected
                  ]}
                  onPress={() => {
                    setStrategy(option);
                    setShowDropdown(false);
                  }}
                >
                  <Text style={[
                    styles.dropdownItemText,
                    strategy === option && styles.dropdownItemTextSelected
                  ]}>
                    {option}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          )}
        </View>

        {/* Feature 3: Action Trigger */}
        <TouchableOpacity
          style={styles.optimizeButton}
          onPress={() => {
            router.push({
              pathname: '/results',
              params: {
                selectedStores: JSON.stringify(selectedStores),
                strategy: strategy
              }
            });
          }}
        >
          <Text style={styles.optimizeButtonText}>Optimize Current Shopping List</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
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
    marginBottom: 32,
    ...Platform.select({
      web: {
        textAlign: 'center' as any,
      }
    })
  },
  headerTitle: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#1A1A1A',
    fontFamily: 'Fraunces-Bold',
    letterSpacing: 0.5,
  },
  headerSub: {
    color: '#666',
    marginTop: 4,
    fontSize: 14,
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
  cardHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  cardTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#333333',
    fontFamily: 'Fraunces-Bold',
  },
  backButton: {
    padding: 4,
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
  storeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  storeButton: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: ACCENT_ORANGE,
    backgroundColor: '#FFFFFF',
  },
  storeButtonSelected: {
    backgroundColor: ACCENT_ORANGE,
  },
  storeButtonText: {
    color: ACCENT_ORANGE,
    fontWeight: '600',
    fontSize: 13,
  },
  storeButtonTextSelected: {
    color: '#FFFFFF',
  },
  dropdownSelector: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#CCCCCC',
    borderRadius: 8,
    padding: 12,
    backgroundColor: '#FFFFFF',
  },
  dropdownSelectorText: {
    fontSize: 14,
    color: '#333333',
    flex: 1,
    marginRight: 8,
  },
  dropdown: {
    borderWidth: 1,
    borderColor: '#CCCCCC',
    borderTopWidth: 0,
    borderRadius: 8,
    marginTop: 4,
    backgroundColor: '#FFFFFF',
    overflow: 'hidden',
  },
  dropdownItem: {
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#EEEEEE',
  },
  dropdownItemSelected: {
    backgroundColor: '#FFF5E6',
  },
  dropdownItemText: {
    fontSize: 13,
    color: '#666666',
  },
  dropdownItemTextSelected: {
    color: ACCENT_ORANGE,
    fontWeight: '600',
  },
  optimizeButton: {
    marginTop: 12,
    backgroundColor: ACCENT_ORANGE,
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: 'center',
  },
  optimizeButtonText: {
    color: '#FFFFFF',
    fontWeight: 'bold',
    fontSize: 15,
  },
});
