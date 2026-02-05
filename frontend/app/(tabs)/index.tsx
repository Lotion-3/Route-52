import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, Switch } from 'react-native';
import { useRouter } from 'expo-router';
import { useFonts, EBGaramond_400Regular, EBGaramond_700Bold } from '@expo-google-fonts/eb-garamond';
import { Colors } from '@/constants/theme';
import { IconSymbol } from '@/components/ui/icon-symbol';

const CustomRadioButton = ({ label, selected, onSelect }: { label: string; selected: boolean; onSelect: () => void }) => (
  <TouchableOpacity style={styles.radioContainer} onPress={onSelect}>
    <View style={[styles.radioButton, selected && styles.radioButtonSelected]}>
      {selected && <View style={styles.radioButtonInner} />}
    </View>
    <Text style={styles.radioLabel}>{label}</Text>
  </TouchableOpacity>
);

export default function SearchScreen() {
  const [budget, setBudget] = useState('');
  const [time, setTime] = useState('');
  const [location, setLocation] = useState('');

  // New preference states
  const [dietaryRestrictions, setDietaryRestrictions] = useState('');
  const [cuisines, setCuisines] = useState('');
  const [experiment, setExperiment] = useState(true);
  const [cookTime, setCookTime] = useState('30-45 minutes');
  const [daysPlan, setDaysPlan] = useState('7');
  const [mealsPerDay, setMealsPerDay] = useState('3');
  const [calories, setCalories] = useState('2000');

  // Calorie Calculator states
  const [showCalculator, setShowCalculator] = useState(false);
  const [weight, setWeight] = useState('');
  const [heightFt, setHeightFt] = useState('');
  const [heightIn, setHeightIn] = useState('');
  const [age, setAge] = useState('');
  const [gender, setGender] = useState('M');
  const [activityLevel, setActivityLevel] = useState('2');
  const [goal, setGoal] = useState('2');

  const router = useRouter();

  // Fonts are now loaded in app/_layout.tsx for global availability


  const calculateTDEE = () => {
    try {
      const w = parseFloat(weight) * 0.453592;
      const h = ((parseInt(heightFt) * 12) + parseInt(heightIn)) * 2.54;
      const a = parseInt(age);

      let bmr = 0;
      if (gender === 'M') {
        bmr = (10 * w) + (6.25 * h) - (5 * a) + 5;
      } else {
        bmr = (10 * w) + (6.25 * h) - (5 * a) - 161;
      }

      const multipliers: { [key: string]: number } = { '1': 1.2, '2': 1.375, '3': 1.55, '4': 1.725 };
      let tdee = bmr * (multipliers[activityLevel] || 1.375);

      if (goal === '1') tdee -= 500;
      else if (goal === '3') tdee += 500;

      const finalCal = Math.max(1200, Math.round(tdee));
      setCalories(finalCal.toString());
      setShowCalculator(false);
    } catch (e) {
      alert("Please fill in all calorie calculator fields correctly.");
    }
  };

  const handleSearch = () => {
    if (!budget && !time && !location) return;
    router.push({
      pathname: '/results',
      params: {
        budget,
        time,
        location,
        dietary_restrictions: dietaryRestrictions,
        cuisines,
        experiment: experiment ? 'true' : 'false',
        cook_time: cookTime,
        days: daysPlan,
        meals_per_day: mealsPerDay,
        calories
      }
    });
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={styles.container}
    >
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
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
                placeholder="Address or Zip Code"
                placeholderTextColor="#94A3B8"
                value={location}
                onChangeText={setLocation}
              />
            </View>
          </View>

          <View style={styles.row}>
            <View style={[styles.inputGroup, { flex: 1, marginRight: 10 }]}>
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

            <View style={[styles.inputGroup, { flex: 1 }]}>
              <Text style={styles.label}>Shopping Time</Text>
              <View style={styles.inputWrapper}>
                <IconSymbol name="clock.fill" size={18} color="#94A3B8" style={{ marginLeft: 15 }} />
                <TextInput
                  style={[styles.input, { paddingLeft: 10 }]}
                  placeholder="3 hrs"
                  placeholderTextColor="#94A3B8"
                  keyboardType="numeric"
                  value={time}
                  onChangeText={setTime}
                />
              </View>
            </View>
          </View>

          <View style={styles.divider} />

          <Text style={styles.sectionTitle}>Diet & Preferences</Text>

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Dietary Restrictions</Text>
            <View style={styles.inputWrapper}>
              <TextInput
                style={styles.input}
                placeholder="Vegan, Gluten-free, No peanuts"
                placeholderTextColor="#94A3B8"
                value={dietaryRestrictions}
                onChangeText={setDietaryRestrictions}
              />
            </View>
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Preferred Cuisines</Text>
            <View style={styles.inputWrapper}>
              <TextInput
                style={styles.input}
                placeholder="Italian, Mexican, Asian"
                placeholderTextColor="#94A3B8"
                value={cuisines}
                onChangeText={setCuisines}
              />
            </View>
          </View>

          <View style={styles.row}>
            <View style={[styles.inputGroup, { flex: 1, marginRight: 10 }]}>
              <Text style={styles.label}>Meal Plan Days</Text>
              <View style={styles.inputWrapper}>
                <TextInput
                  style={styles.input}
                  placeholder="7"
                  placeholderTextColor="#94A3B8"
                  keyboardType="numeric"
                  value={daysPlan}
                  onChangeText={setDaysPlan}
                />
              </View>
            </View>
            <View style={[styles.inputGroup, { flex: 1 }]}>
              <Text style={styles.label}>Meals/Day</Text>
              <View style={styles.inputWrapper}>
                <TextInput
                  style={styles.input}
                  placeholder="3"
                  placeholderTextColor="#94A3B8"
                  keyboardType="numeric"
                  value={mealsPerDay}
                  onChangeText={setMealsPerDay}
                />
              </View>
            </View>
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Max Cook Time / Meal</Text>
            <View style={styles.inputWrapper}>
              <TextInput
                style={styles.input}
                placeholder="30-45 minutes"
                placeholderTextColor="#94A3B8"
                value={cookTime}
                onChangeText={setCookTime}
              />
            </View>
          </View>

          <View style={styles.switchGroup}>
            <Text style={styles.label}>Explore New Recipes?</Text>
            <Switch
              value={experiment}
              onValueChange={setExperiment}
              trackColor={{ false: '#CBD5E1', true: Colors.primary }}
              thumbColor={Platform.OS === 'ios' ? '#FFFFFF' : experiment ? Colors.primary : '#F4F3F4'}
            />
          </View>

          <View style={styles.divider} />

          <View style={styles.nutritionHeader}>
            <Text style={styles.sectionTitle}>Daily Calorie Target</Text>
            <TouchableOpacity onPress={() => setShowCalculator(!showCalculator)}>
              <Text style={styles.calcToggle}>{showCalculator ? "Hide Calc" : "Open Calculator"}</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.inputWrapper}>
            <TextInput
              style={styles.input}
              placeholder="2000"
              placeholderTextColor="#94A3B8"
              keyboardType="numeric"
              value={calories}
              onChangeText={setCalories}
            />
          </View>

          {showCalculator && (
            <View style={styles.calculatorCard}>
              <Text style={styles.calcTitle}>Calorie Calculator</Text>

              <View style={styles.row}>
                <View style={[styles.inputGroup, { flex: 1, marginRight: 10 }]}>
                  <Text style={styles.labelSmall}>Weight (lbs)</Text>
                  <TextInput style={styles.calcInput} keyboardType="numeric" value={weight} onChangeText={setWeight} />
                </View>
                <View style={[styles.inputGroup, { flex: 0.5, marginRight: 10 }]}>
                  <Text style={styles.labelSmall}>Ft</Text>
                  <TextInput style={styles.calcInput} keyboardType="numeric" value={heightFt} onChangeText={setHeightFt} />
                </View>
                <View style={[styles.inputGroup, { flex: 0.5 }]}>
                  <Text style={styles.labelSmall}>In</Text>
                  <TextInput style={styles.calcInput} keyboardType="numeric" value={heightIn} onChangeText={setHeightIn} />
                </View>
              </View>

              <View style={styles.row}>
                <View style={[styles.inputGroup, { flex: 1, marginRight: 10 }]}>
                  <Text style={styles.labelSmall}>Age</Text>
                  <TextInput style={styles.calcInput} keyboardType="numeric" value={age} onChangeText={setAge} />
                </View>
                <View style={[styles.inputGroup, { flex: 1 }]}>
                  <Text style={styles.labelSmall}>Gender</Text>
                  <View style={styles.radioGroup}>
                    <CustomRadioButton label="M" selected={gender === 'M'} onSelect={() => setGender('M')} />
                    <CustomRadioButton label="F" selected={gender === 'F'} onSelect={() => setGender('F')} />
                  </View>
                </View>
              </View>

              <Text style={styles.labelSmall}>Activity Level</Text>
              <View style={styles.radioGrid}>
                <CustomRadioButton label="Sedentary" selected={activityLevel === '1'} onSelect={() => setActivityLevel('1')} />
                <CustomRadioButton label="Light" selected={activityLevel === '2'} onSelect={() => setActivityLevel('2')} />
                <CustomRadioButton label="Moderate" selected={activityLevel === '3'} onSelect={() => setActivityLevel('3')} />
                <CustomRadioButton label="Active" selected={activityLevel === '4'} onSelect={() => setActivityLevel('4')} />
              </View>

              <Text style={styles.labelSmall}>Goal</Text>
              <View style={styles.radioGrid}>
                <CustomRadioButton label="Lose Weight" selected={goal === '1'} onSelect={() => setGoal('1')} />
                <CustomRadioButton label="Maintain" selected={goal === '2'} onSelect={() => setGoal('2')} />
                <CustomRadioButton label="Gain Weight" selected={goal === '3'} onSelect={() => setGoal('3')} />
              </View>

              <TouchableOpacity style={styles.calcButton} onPress={calculateTDEE}>
                <Text style={styles.calcButtonText}>Apply Results</Text>
              </TouchableOpacity>
            </View>
          )}

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
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  scrollContent: {
    padding: 24,
    paddingTop: 60,
    paddingBottom: 40,
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
    fontSize: 12,
    fontWeight: '700',
    color: Colors.text,
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: Colors.text,
    marginBottom: 16,
    marginTop: 10,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
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
    fontSize: 16,
    color: Colors.text,
    fontWeight: '500',
  },
  divider: {
    height: 1,
    backgroundColor: Colors.border,
    marginVertical: 10,
    opacity: 0.5,
  },
  switchGroup: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
  },
  nutritionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  calcToggle: {
    color: Colors.primary,
    fontWeight: '600',
    fontSize: 12,
  },
  button: {
    backgroundColor: Colors.primary,
    height: 56,
    borderRadius: 14,
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 20,
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
  },
  // Radio Button Styles
  radioContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 15,
    marginBottom: 10,
  },
  radioButton: {
    height: 20,
    width: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: Colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
  },
  radioButtonSelected: {
    borderColor: Colors.primary,
  },
  radioButtonInner: {
    height: 10,
    width: 10,
    borderRadius: 5,
    backgroundColor: Colors.primary,
  },
  radioLabel: {
    fontSize: 14,
    color: Colors.text,
  },
  radioGroup: {
    flexDirection: 'row',
    height: 48,
    alignItems: 'center',
  },
  radioGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginTop: 5,
    marginBottom: 15,
  },
  // Calculator Styles
  calculatorCard: {
    backgroundColor: '#F1F5F9',
    borderRadius: 16,
    padding: 16,
    marginTop: 15,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  calcTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: Colors.text,
    marginBottom: 15,
  },
  labelSmall: {
    fontSize: 11,
    fontWeight: '700',
    color: Colors.textLight,
    marginBottom: 4,
    textTransform: 'uppercase',
  },
  calcInput: {
    backgroundColor: '#FFF',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: Colors.border,
    height: 40,
    paddingHorizontal: 10,
    fontSize: 14,
  },
  calcButton: {
    backgroundColor: Colors.text,
    height: 40,
    borderRadius: 8,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 10,
  },
  calcButtonText: {
    color: '#FFF',
    fontSize: 14,
    fontWeight: 'bold',
  }
});