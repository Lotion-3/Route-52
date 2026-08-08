import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, TextInput } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import Logo from '@/components/Logo';
import TopBanner from '@/components/TopBanner';
import GradientButton from '@/components/GradientButton';
import { autocompleteAddress } from '@/services/api';

// Brand & styling constants
const ACCENT_ORANGE = '#EA7000'; // Matching orange from design
const BG_CREAM = '#FFF2E0';

type StrategyOption =
  | 'Lowest Total Cost (Split items across multiple stores)'
  | 'Single Store Speed (Fastest shopping trip)';



export default function GroceryStoreOptimizerView() {
  const router = useRouter();
  const [selectedStores, setSelectedStores] = useState<string[]>([]);
  const [strategy, setStrategy] = useState<StrategyOption>('Lowest Total Cost (Split items across multiple stores)');
  const [showDropdown, setShowDropdown] = useState(false);
  const [location, setLocation] = useState('');
  const [time, setTime] = useState('3');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const suppressFetch = useRef(false);

  // Address autocomplete logic
  useEffect(() => {
    if (suppressFetch.current) {
      suppressFetch.current = false;
      return;
    }
    const q = location.trim();
    if (q.length < 3) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    const t = setTimeout(async () => {
      const next = await autocompleteAddress(q, controller.signal);
      if (!cancelled) setSuggestions(next);
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
      controller.abort();
    };
  }, [location]);

  const selectSuggestion = (s: string) => {
    suppressFetch.current = true;
    setLocation(s);
    setSuggestions([]);
  };

  const stores = ['Aldi', 'Kroger', "Trader Joe's", 'Walmart'];

  const strategies: StrategyOption[] = [
    'Lowest Total Cost (Split items across multiple stores)',
    'Single Store Speed (Fastest shopping trip)'
  ];

  const toggleStore = (store: string) => {
    if (selectedStores.includes(store)) {
      setSelectedStores(selectedStores.filter((s) => s !== store));
    } else {
      setSelectedStores([...selectedStores, store]);
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: BG_CREAM }}>
      <TopBanner title="Homepage" />

      <ScrollView contentContainerStyle={[styles.container, { paddingTop: 92 }]} showsVerticalScrollIndicator={false}>
        <Stack.Screen options={{ headerShown: false }} />


        {/* Header Logo Section */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.push('/')}>
            <Logo size={288} />
          </TouchableOpacity>
        </View>

        {/* Page Title Section */}
        <Text style={styles.pageTitle}>Grocery List Optimizer</Text>

        {/* Main Container resembling the provided HTML card */}
        <View style={styles.card}>


          {/* Your Location */}
          <View style={styles.section}>
            <Text style={styles.label}>Your Location</Text>
            <View style={styles.inputRow}>
              <Ionicons name="location-outline" size={18} color="#9CA3AF" />
              <TextInput
                placeholder="Address or Zip Code"
                placeholderTextColor="#9CA3AF"
                style={styles.iconInput}
                value={location}
                onChangeText={setLocation}
                returnKeyType="next"
              />
            </View>
            {suggestions.length > 0 && (
              <View style={styles.suggestBox}>
                {suggestions.map((s) => (
                  <TouchableOpacity
                    key={s}
                    style={styles.suggestItem}
                    onPress={() => selectSuggestion(s)}
                  >
                    <Ionicons name="location-outline" size={15} color="#9CA3AF" />
                    <Text style={styles.suggestText} numberOfLines={1}>{s}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            )}
          </View>

          {/* Shopping Time */}
          <View style={styles.section}>
            <Text style={styles.label}>Shopping Time (hrs)</Text>
            <View style={styles.inputRow}>
              <Ionicons name="time-outline" size={18} color="#9CA3AF" />
              <TextInput
                placeholder="3"
                placeholderTextColor="#9CA3AF"
                style={styles.iconInput}
                keyboardType="numeric"
                value={time}
                onChangeText={setTime}
              />
            </View>
          </View>

          {/* Feature 1: Store Selection */}
        <View style={styles.section}>
          <Text style={styles.label}>Preferred Nearby Stores</Text>
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
        <View style={{ marginTop: 12 }}>
          <GradientButton
            title="Optimize Shopping List"
            onPress={() => {
              router.push({
                pathname: '/optimizer_search',
                params: {
                  selectedStores: JSON.stringify(selectedStores),
                  strategy: strategy,
                  location: location,
                  time: time
                }
              });
            }}
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
    marginBottom: -30,
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
  suggestBox: {
    marginTop: 8,
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    overflow: 'hidden',
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
    flex: 1,
    fontSize: 14,
    color: '#374151',
  },
});
