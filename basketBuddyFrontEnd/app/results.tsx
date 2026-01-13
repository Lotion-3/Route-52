import React from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity } from 'react-native';
import { Stack, useRouter, useLocalSearchParams } from 'expo-router';

export default function ResultsScreen() {
  const router = useRouter();
  const { budget, time } = useLocalSearchParams(); // This grabs the budget and time
  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

  // This is a special component for the bottom of the list
  const ListFooter = () => (
    <TouchableOpacity 
      style={styles.backButton} 
      onPress={() => router.dismissAll()} // Clears the stack and goes back to index
    >
      <Text style={styles.backButtonText}>BACK TO START</Text>
    </TouchableOpacity>
  );

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: 'Your Plan' }} />

      <View style={styles.headerInfo}>
        <Text style={styles.infoText}>Budget: ${budget || '0'}</Text>
        <Text style={styles.infoText}>Time: {time || '0'} mins</Text>
      </View>

      <FlatList 
        data={days}
        keyExtractor={(item) => item}
        renderItem={({ item }) => (
          <View style={styles.dayRow}>
            <Text style={styles.dayText}>{item}</Text>
            <View style={styles.boxContainer}>
              <View style={styles.box}><Text style={styles.boxText}>blank</Text></View>
              <View style={styles.box}><Text style={styles.boxText}>blank</Text></View>
              <View style={styles.box}><Text style={styles.boxText}>blank</Text></View>
            </View>
          </View>
        )}
        ListFooterComponent={ListFooter} // Adds button at the end of the scroll
        contentContainerStyle={{ paddingBottom: 40 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff', paddingHorizontal: 15 },
  headerInfo: { flexDirection: 'row', justifyContent: 'space-around', paddingVertical: 15, backgroundColor: '#f0f7ff', borderRadius: 10, marginVertical: 10 },
  infoText: { fontSize: 14, fontWeight: 'bold', color: '#007AFF' },
  dayRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 20, borderBottomWidth: 1, borderBottomColor: '#f0f0f0' },
  dayText: { fontSize: 16, width: 90, fontWeight: '600' },
  boxContainer: { flexDirection: 'row' },
  box: { width: 60, height: 45, backgroundColor: '#f8f9fa', marginHorizontal: 4, justifyContent: 'center', alignItems: 'center', borderRadius: 8, borderWidth: 1, borderColor: '#e9ecef' },
  boxText: { fontSize: 11, color: '#adb5bd' },
  backButton: { backgroundColor: '#333', padding: 15, borderRadius: 10, alignItems: 'center', marginTop: 30 },
  backButtonText: { color: '#fff', fontWeight: 'bold' }
});