import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';

export default function SearchScreen() {
  const [budget, setBudget] = useState('');
  const [time, setTime] = useState('');
  const router = useRouter();

  return (
    <View style={styles.container}>
      <Text style={styles.title}>BasketBuddy</Text>
      
      <Text style={styles.label}>Max Budget ($)</Text>
      <TextInput 
        style={styles.input}
        placeholder="e.g. 50"
        keyboardType="numeric"
        value={budget}
        onChangeText={setBudget}
      />

      <Text style={styles.label}>Max Time (Minutes)</Text>
      <TextInput 
        style={styles.input}
        placeholder="e.g. 30"
        keyboardType="numeric"
        value={time}
        onChangeText={setTime}
      />

      <TouchableOpacity 
        style={styles.button} 
        // We pass the data here as "params"
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
  title: { fontSize: 28, fontWeight: 'bold', textAlign: 'center', marginBottom: 40, color: '#007AFF' },
  label: { fontSize: 16, fontWeight: 'bold', marginBottom: 5 },
  input: { backgroundColor: '#f9f9f9', padding: 15, borderRadius: 10, borderWidth: 1, borderColor: '#eee', marginBottom: 20 },
  button: { backgroundColor: '#007AFF', padding: 18, borderRadius: 10, alignItems: 'center', marginTop: 10 },
  buttonText: { color: '#fff', fontWeight: 'bold', fontSize: 18 },
});