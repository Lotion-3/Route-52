import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, Switch } from 'react-native';
import { useRouter, Stack } from 'expo-router';
import { Colors } from '@/constants/theme';
import Logo from '@/components/Logo';
import { Ionicons } from '@expo/vector-icons';
import GradientButton from '@/components/GradientButton';

const CustomRadioButton = ({ label, selected, onSelect }: { label: string; selected: boolean; onSelect: () => void }) => (
    <TouchableOpacity style={styles.radioContainer} onPress={onSelect}>
        <View style={[styles.radioButton, selected && styles.radioButtonSelected]}>
            {selected && <View style={styles.radioButtonInner} />}
        </View>
        <Text style={styles.radioLabel}>{label}</Text>
    </TouchableOpacity>
);

export default function SearchScreen() {
    const [budget, setBudget] = useState('150');
    const [time, setTime] = useState('3');
    const [location, setLocation] = useState('');

    // New preference states
    const [dietaryRestrictions, setDietaryRestrictions] = useState('');
    const [cuisines, setCuisines] = useState('');
    const [experiment, setExperiment] = useState(true);
    const [cookTime, setCookTime] = useState('30-45 minutes');
    const [daysPlan, setDaysPlan] = useState('7');
    const [mealsPerDay, setMealsPerDay] = useState('3');
    const [calories, setCalories] = useState('2000');
    const [fridgeItems, setFridgeItems] = useState('');
    const [hasFridgeItems, setHasFridgeItems] = useState(false);

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
        if (!budget && !time && !location) {
            alert("Please enter at least one of: Location, Budget, or Time.");
            return;
        }
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
                calories,
                fridge_items: hasFridgeItems ? fridgeItems : ''
            }
        });
    };

    return (
        <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={{ flex: 1 }}
        >
            <Stack.Screen options={{ title: 'New Meal Plan', headerShown: true }} />
            <ScrollView contentContainerStyle={styles.page} showsVerticalScrollIndicator={false}>

                <View style={styles.sectionHead}>
                    <Logo size={80} />
                    <View style={{ height: 8 }} />
                    <Text style={styles.header}>Plan Details</Text>
                </View>

                {/* SECTION 1: Location */}
                <View style={styles.section}>
                    <View style={styles.card}>
                        <Text style={styles.label}>Your Location</Text>
                        <View style={styles.inputRow}>
                            <Ionicons name="location-outline" size={18} color="#9CA3AF" />
                            <TextInput
                                placeholder="Address or Zip Code"
                                placeholderTextColor="#9CA3AF"
                                style={styles.iconInput}
                                value={location}
                                onChangeText={setLocation}
                            />
                        </View>
                    </View>
                </View>

                {/* SECTION 2: Budget & Time */}
                <View style={styles.section}>
                    <View style={styles.card}>
                        <View style={styles.row}>

                            <View style={styles.half}>
                                <Text style={styles.label}>Weekly Budget ($)</Text>
                                <View style={styles.inputRow}>
                                    <Ionicons name="cash-outline" size={18} color="#9CA3AF" />
                                    <TextInput
                                        placeholder="150"
                                        placeholderTextColor="#9CA3AF"
                                        style={styles.iconInput}
                                        keyboardType="numeric"
                                        value={budget}
                                        onChangeText={setBudget}
                                    />
                                </View>
                            </View>

                            <View style={styles.half}>
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

                        </View>
                    </View>
                </View>

                {/* SECTION 3: Diet & Cuisines */}
                <View style={styles.section}>
                    <View style={styles.card}>
                        <Text style={styles.label}>Dietary Restrictions</Text>
                        <View style={[styles.inputRow, { marginBottom: 16 }]}>
                            <Ionicons name="medkit-outline" size={18} color="#9CA3AF" />
                            <TextInput
                                placeholder="Vegan, Gluten-free..."
                                placeholderTextColor="#9CA3AF"
                                style={styles.iconInput}
                                value={dietaryRestrictions}
                                onChangeText={setDietaryRestrictions}
                            />
                        </View>

                        <Text style={styles.label}>Preferred Cuisines</Text>
                        <View style={styles.inputRow}>
                            <Ionicons name="restaurant-outline" size={18} color="#9CA3AF" />
                            <TextInput
                                placeholder="Italian, Mexican, Asian..."
                                placeholderTextColor="#9CA3AF"
                                style={styles.iconInput}
                                value={cuisines}
                                onChangeText={setCuisines}
                            />
                        </View>
                    </View>
                </View>

                {/* SECTION 4: Planning Details */}
                <View style={styles.section}>
                    <View style={styles.card}>
                        <View style={styles.row}>
                            <View style={{ flex: 1, marginRight: 10 }}>
                                <Text style={styles.label}>Days</Text>
                                <View style={styles.inputRow}>
                                    <Ionicons name="calendar-outline" size={18} color="#9CA3AF" />
                                    <TextInput
                                        placeholder="7"
                                        placeholderTextColor="#9CA3AF"
                                        style={styles.iconInput}
                                        keyboardType="numeric"
                                        value={daysPlan}
                                        onChangeText={setDaysPlan}
                                    />
                                </View>
                            </View>
                            <View style={{ flex: 1 }}>
                                <Text style={styles.label}>Meals/Day</Text>
                                <View style={styles.inputRow}>
                                    <Ionicons name="fast-food-outline" size={18} color="#9CA3AF" />
                                    <TextInput
                                        placeholder="3"
                                        placeholderTextColor="#9CA3AF"
                                        style={styles.iconInput}
                                        keyboardType="numeric"
                                        value={mealsPerDay}
                                        onChangeText={setMealsPerDay}
                                    />
                                </View>
                            </View>
                        </View>

                        <View style={{ marginTop: 16 }}>
                            <Text style={styles.label}>Max Cook Time</Text>
                            <View style={styles.inputRow}>
                                <Ionicons name="alarm-outline" size={18} color="#9CA3AF" />
                                <TextInput
                                    placeholder="30-45 minutes"
                                    placeholderTextColor="#9CA3AF"
                                    style={styles.iconInput}
                                    value={cookTime}
                                    onChangeText={setCookTime}
                                />
                            </View>
                        </View>

                        <View style={[styles.switchGroup, { marginTop: 16 }]}>
                            <Text style={styles.label}>Explore New Recipes?</Text>
                            <Switch
                                value={experiment}
                                onValueChange={setExperiment}
                                trackColor={{ false: '#CBD5E1', true: '#1F2933' }}
                                thumbColor={'#FFFFFF'}
                            />
                        </View>

                        <View style={[styles.switchGroup, { marginTop: 16 }]}>
                            <Text style={styles.label}>Any ingredients at home?</Text>
                            <Switch
                                value={hasFridgeItems}
                                onValueChange={setHasFridgeItems}
                                trackColor={{ false: '#CBD5E1', true: '#1F2933' }}
                                thumbColor={'#FFFFFF'}
                            />
                        </View>

                        {hasFridgeItems && (
                            <View style={{ marginTop: 16 }}>
                                <Text style={styles.label}>Enter items (comma separated)</Text>
                                <View style={styles.inputRow}>
                                    <Ionicons name="leaf-outline" size={18} color="#9CA3AF" />
                                    <TextInput
                                        placeholder="e.g. Eggs, Onion, Milk..."
                                        placeholderTextColor="#9CA3AF"
                                        style={styles.iconInput}
                                        multiline
                                        value={fridgeItems}
                                        onChangeText={setFridgeItems}
                                    />
                                </View>
                            </View>
                        )}
                    </View>
                </View>

                {/* SECTION 5: Calories */}
                <View style={styles.section}>
                    <View style={styles.card}>
                        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                            <Text style={styles.label}>Daily Calorie Target</Text>
                            <TouchableOpacity onPress={() => setShowCalculator(!showCalculator)}>
                                <Text style={styles.linkText}>{showCalculator ? "Hide Calc" : "Calculator"}</Text>
                            </TouchableOpacity>
                        </View>

                        <View style={styles.inputRow}>
                            <Ionicons name="flame-outline" size={18} color="#9CA3AF" />
                            <TextInput
                                placeholder="2000"
                                placeholderTextColor="#9CA3AF"
                                style={styles.iconInput}
                                keyboardType="numeric"
                                value={calories}
                                onChangeText={setCalories}
                            />
                        </View>

                        {showCalculator && (
                            <View style={styles.calculatorSection}>
                                <Text style={styles.sectionTitle}>Calculator</Text>

                                <View style={styles.row}>
                                    <View style={{ flex: 1, marginRight: 8 }}>
                                        <Text style={styles.labelSmall}>Weight (lbs)</Text>
                                        <TextInput style={styles.calcInput} keyboardType="numeric" value={weight} onChangeText={setWeight} />
                                    </View>
                                    <View style={{ flex: 0.5, marginRight: 8 }}>
                                        <Text style={styles.labelSmall}>Ft</Text>
                                        <TextInput style={styles.calcInput} keyboardType="numeric" value={heightFt} onChangeText={setHeightFt} />
                                    </View>
                                    <View style={{ flex: 0.5 }}>
                                        <Text style={styles.labelSmall}>In</Text>
                                        <TextInput style={styles.calcInput} keyboardType="numeric" value={heightIn} onChangeText={setHeightIn} />
                                    </View>
                                </View>

                                <View style={[styles.row, { marginTop: 12 }]}>
                                    <View style={{ flex: 1, marginRight: 8 }}>
                                        <Text style={styles.labelSmall}>Age</Text>
                                        <TextInput style={styles.calcInput} keyboardType="numeric" value={age} onChangeText={setAge} />
                                    </View>
                                    <View style={{ flex: 1 }}>
                                        <Text style={styles.labelSmall}>Gender</Text>
                                        <View style={{ flexDirection: 'row' }}>
                                            <CustomRadioButton label="M" selected={gender === 'M'} onSelect={() => setGender('M')} />
                                            <CustomRadioButton label="F" selected={gender === 'F'} onSelect={() => setGender('F')} />
                                        </View>
                                    </View>
                                </View>

                                <Text style={[styles.labelSmall, { marginTop: 12 }]}>Activity Level</Text>
                                <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 8 }}>
                                    <CustomRadioButton label="Sedentary" selected={activityLevel === '1'} onSelect={() => setActivityLevel('1')} />
                                    <CustomRadioButton label="Light" selected={activityLevel === '2'} onSelect={() => setActivityLevel('2')} />
                                    <CustomRadioButton label="Moderate" selected={activityLevel === '3'} onSelect={() => setActivityLevel('3')} />
                                    <CustomRadioButton label="Active" selected={activityLevel === '4'} onSelect={() => setActivityLevel('4')} />
                                </View>

                                <Text style={[styles.labelSmall, { marginTop: 4 }]}>Goal</Text>
                                <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 12 }}>
                                    <CustomRadioButton label="Lose" selected={goal === '1'} onSelect={() => setGoal('1')} />
                                    <CustomRadioButton label="Maintain" selected={goal === '2'} onSelect={() => setGoal('2')} />
                                    <CustomRadioButton label="Gain" selected={goal === '3'} onSelect={() => setGoal('3')} />
                                </View>

                                <TouchableOpacity style={styles.calcButton} onPress={calculateTDEE}>
                                    <Text style={styles.calcButtonText}>Apply Results</Text>
                                </TouchableOpacity>
                            </View>
                        )}
                    </View>
                </View>

                <GradientButton
                    title="Generate Plan →"
                    onPress={handleSearch}
                />

            </ScrollView>
        </KeyboardAvoidingView>
    );
}

const styles = StyleSheet.create({
    page: {
        backgroundColor: '#F7F2EA',
        padding: 20,
        paddingTop: 20,
        flexGrow: 1,
    },

    sectionHead: {
        marginBottom: 32,
        alignItems: 'center',
    },

    header: {
        fontSize: 28,
        fontWeight: '700',
        color: '#1F2933',
        fontFamily: 'Garamond-Bold',
        marginTop: 16,
    },

    section: {
        marginBottom: 16,
    },

    card: {
        backgroundColor: '#FEFEFC',
        borderRadius: 18,
        padding: 18,
        marginBottom: 8,

        // soft shadow (iOS)
        shadowColor: '#000',
        shadowOpacity: 0.05,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 6 },

        // Android
        elevation: 4,
    },

    label: {
        fontSize: 14,
        fontWeight: '600',
        color: '#6B7280',
        marginBottom: 8,
    },

    inputRow: {
        flexDirection: 'row',
        alignItems: 'center',
        borderWidth: 1,
        borderColor: '#E5E7EB',
        borderRadius: 12,
        paddingHorizontal: 12,
        backgroundColor: '#FAFAFA',
    },

    iconInput: {
        flex: 1,
        marginLeft: 10,
        paddingVertical: 14,
        fontSize: 16,
        color: '#111827',
    },

    // Additional styles needed for functionality
    row: {
        flexDirection: 'row',
        gap: 14,
    },

    half: {
        flex: 1,
    },

    switchGroup: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
    },

    linkText: {
        color: '#1F2933',
        fontWeight: '600',
        fontSize: 12,
        textDecorationLine: 'underline',
    },

    // Calculator Styles
    calculatorSection: {
        marginTop: 16,
        paddingTop: 16,
        borderTopWidth: 1,
        borderTopColor: '#E5E7EB',
    },
    sectionTitle: {
        fontSize: 16,
        fontWeight: 'bold',
        color: '#1F2933',
        marginBottom: 12,
    },
    labelSmall: {
        fontSize: 12,
        fontWeight: '600',
        color: '#6B7280',
        marginBottom: 4,
    },
    calcInput: {
        backgroundColor: '#FAFAFA',
        borderRadius: 8,
        borderWidth: 1,
        borderColor: '#E5E7EB',
        height: 40,
        paddingHorizontal: 10,
        fontSize: 14,
    },
    calcButton: {
        backgroundColor: '#1F2933',
        height: 44,
        borderRadius: 10,
        justifyContent: 'center',
        alignItems: 'center',
        marginTop: 12,
    },
    calcButtonText: {
        color: '#FFF',
        fontSize: 14,
        fontWeight: 'bold',
    },

    // Custom Radio Button
    radioContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        marginRight: 16,
        marginBottom: 8,
    },
    radioButton: {
        height: 20,
        width: 20,
        borderRadius: 10,
        borderWidth: 2,
        borderColor: '#D1D5DB',
        alignItems: 'center',
        justifyContent: 'center',
        marginRight: 8,
    },
    radioButtonSelected: {
        borderColor: '#1F2933',
    },
    radioButtonInner: {
        height: 10,
        width: 10,
        borderRadius: 5,
        backgroundColor: '#1F2933',
    },
    radioLabel: {
        fontSize: 14,
        color: '#4B5563',
    },
});
