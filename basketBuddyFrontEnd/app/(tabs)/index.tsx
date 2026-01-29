import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, KeyboardAvoidingView, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { useFonts, EBGaramond_400Regular, EBGaramond_700Bold } from '@expo-google-fonts/eb-garamond';
import { Colors } from '@/constants/theme';
import { IconSymbol } from '@/components/ui/icon-symbol';



export default function SearchScreen() {
  const [budget, setBudget] = useState('');
  const [time, setTime] = useState('');
  const [location, setLocation] = useState('');
  const router = useRouter();

  let [fontsLoaded] = useFonts({
    'Garamond-Regular': EBGaramond_400Regular,
    'Garamond-Bold': EBGaramond_700Bold,
  });

  if (!fontsLoaded) {
    return null;
  }

  const handleSearch = () => {
    if (!budget && !time && !location) return;
    router.push({
      pathname: '/results',
      params: { budget, time, location }
    });
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={styles.container}
    >
      <View style={styles.header}>
        <View style={styles.logoCircle}>
          <IconSymbol name="basket.fill" size={40} color={Colors.primary} />
        </View>
        <Text style={styles.title}>BasketBuddies</Text>
        <Text style={styles.subtitle}>Smart Grocery Planning</Text>
      </View>

      <View style={styles.card}>
        <View style={styles.inputGroup}>
          <Text style={styles.label}>Your Location</Text>
          <View style={styles.inputWrapper}>
            <IconSymbol name="house.fill" size={18} color="#94A3B8" style={{ marginLeft: 15 }} />
            <TextInput
              style={[styles.input, { paddingLeft: 10 }]}
              placeholder="Zip Code or City"
              placeholderTextColor="#94A3B8"
              value={location}
              onChangeText={setLocation}
            />
          </View>
        </View>

        <View style={styles.inputGroup}>
          <Text style={styles.label}>Weekly Budget</Text>
          <View style={styles.inputWrapper}>
            <Text style={styles.currency}>$</Text>
            <TextInput
              style={styles.input}
              placeholder="150"
              placeholderTextColor="#94A3B8"
              keyboardType="numeric"
              value={budget}
              onChangeText={setBudget}
            />
          </View>
        </View>

        <View style={styles.inputGroup}>
          <Text style={styles.label}>Shopping Time</Text>
          <View style={styles.inputWrapper}>
            <IconSymbol name="clock.fill" size={18} color="#94A3B8" style={{ marginLeft: 15 }} />
            <TextInput
              style={[styles.input, { paddingLeft: 10 }]}
              placeholder="30 mins"
              placeholderTextColor="#94A3B8"
              keyboardType="numeric"
              value={time}
              onChangeText={setTime}
            />
          </View>
        </View>

        <TouchableOpacity
          style={styles.button}
          onPress={handleSearch}
          activeOpacity={0.8}
        >
          <Text style={styles.buttonText}>Generate Plan</Text>
          <IconSymbol name="arrow.right" size={20} color="#FFF" />
        </TouchableOpacity>
      </View>

      <Text style={styles.footerText}>Powered by Google Gemini</Text>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
    justifyContent: 'center',
    padding: 24
  },
  header: {
    alignItems: 'center',
    marginBottom: 40,
  },
  logoCircle: {
    width: 80,
    height: 80,
    backgroundColor: 'rgba(0, 82, 255, 0.1)',
    borderRadius: 40,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  title: {
    fontSize: 42,
    fontFamily: 'Garamond-Bold',
    color: Colors.primary,
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 16,
    color: Colors.textLight,
    letterSpacing: 0.5,
  },
  card: {
    backgroundColor: Colors.card,
    borderRadius: 24,
    padding: 24,
    shadowColor: Colors.primary,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.08,
    shadowRadius: 24,
    elevation: 8,
  },
  inputGroup: {
    marginBottom: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.text,
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  inputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.background,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: Colors.border,
    height: 56,
  },
  currency: {
    fontSize: 20,
    color: Colors.text,
    marginLeft: 16,
    fontWeight: '600',
  },
  input: {
    flex: 1,
    height: '100%',
    paddingHorizontal: 16,
    fontSize: 18,
    color: Colors.text,
    fontWeight: '500',
  },
  button: {
    backgroundColor: Colors.primary,
    height: 56,
    borderRadius: 14,
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 12,
    shadowColor: Colors.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.2,
    shadowRadius: 8,
    elevation: 4,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginRight: 8,
  },
  footerText: {
    textAlign: 'center',
    marginTop: 32,
    color: Colors.textLight,
    fontSize: 12,
    opacity: 0.6
  }
});