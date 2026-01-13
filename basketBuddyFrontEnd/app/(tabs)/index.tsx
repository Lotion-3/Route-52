import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
// 1. Import the font loading hooks and the specific font
import { useFonts, EBGaramond_400Regular, EBGaramond_700Bold } from '@expo-google-fonts/eb-garamond';

export default function SearchScreen() {
  const [budget, setBudget] = useState('');
  const [time, setTime] = useState('');
  const router = useRouter();

  // 2. Load the fonts
  let [fontsLoaded] = useFonts({
    'Garamond-Regular': EBGaramond_400Regular,
    'Garamond-Bold': EBGaramond_700Bold,
  });

  // 3. Wait for fonts to load before showing the screen
  if (!fontsLoaded) {
    return null; 
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>BasketBuddy</Text>
      
      <Text style={styles.label}>Max Budget ($)</Text>
      <TextInput 
        style={styles.input}
        placeholder="e.g. 50"
        placeholderTextColor="#999"
        keyboardType="numeric"
        value={budget}
        onChangeText={setBudget}
      />

      <Text style={styles.label}>Max Time (Minutes)</Text>
      <TextInput 
        style={styles.input}
        placeholder="e.g. 30"
        placeholderTextColor="#999"
        keyboardType="numeric"
        value={time}
        onChangeText={setTime}
      />

      <TouchableOpacity 
        style={styles.button} 
        onPress={() => router.push({
          pathname: '/results',
          params: { budget, time }
        })}
      >
        <Text style={styles.buttonText}>SEARCH</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, backgroundColor: '#fff', justifyContent: 'center' },
  title: { 
    fontSize: 34, 
    fontFamily: 'Garamond-Bold', // Use the loaded font name
    textAlign: 'center', 
    marginBottom: 40, 
    color: '#007AFF' 
  },
  label: { 
    fontSize: 18, 
    fontFamily: 'Garamond-Bold', 
    marginBottom: 5 
  },
  input: { 
    backgroundColor: '#f9f9f9', 
    padding: 15, 
    borderRadius: 10, 
    borderWidth: 1, 
    borderColor: '#eee', 
    marginBottom: 20,
    fontFamily: 'Garamond-Regular', // Font for the typing area
    fontSize: 16
  },
  button: { 
    backgroundColor: '#007AFF', 
    padding: 18, 
    borderRadius: 10, 
    alignItems: 'center', 
    marginTop: 10 
  },
  buttonText: { 
    color: '#fff', 
    fontSize: 20, 
    fontFamily: 'Garamond-Bold' 
  },
});