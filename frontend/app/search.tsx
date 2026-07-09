import React, { useState, useMemo } from 'react';
import {
    View, Text, TextInput, TouchableOpacity, StyleSheet,
    KeyboardAvoidingView, Platform, ScrollView, Switch,
    Modal, FlatList, SafeAreaView,
} from 'react-native';
import { useRouter, Stack, useLocalSearchParams } from 'expo-router';
import Logo from '@/components/Logo';
import { Ionicons } from '@expo/vector-icons';
import GradientButton from '@/components/GradientButton';
import TopBanner from '@/components/TopBanner';
import LoadingGate from '@/components/LoadingGate';

// ── Static option lists ──────────────────────────────────────────────────────

const ALLERGEN_OPTIONS = [
    'Milk / Dairy', 'Eggs', 'Fish', 'Shellfish', 'Tree Nuts', 'Peanuts',
    'Wheat / Gluten', 'Soy', 'Sesame', 'Mustard', 'Celery', 'Lupin',
    'Molluscs', 'Sulfites', 'Corn', 'Nightshades', 'Citrus', 'Stone Fruits',
    'Coconut', 'Legumes',
];

const HEALTH_OPTIONS = [
    'Diabetes', 'Pre-Diabetes', 'Hypertension', 'Heart Disease', 'High Cholesterol',
    'IBS', 'Celiac Disease', 'GERD / Acid Reflux', 'Kidney Disease', "Crohn's Disease",
    'Thyroid Issues', 'Anemia', 'Lactose Intolerance', 'Gout', 'PCOS',
    'Fatty Liver Disease', 'Diverticulitis', 'Osteoporosis', 'Arthritis',
    'Eczema / Psoriasis', 'Migraines', 'Fibromyalgia', 'Epilepsy',
    'Autism Spectrum', 'ADHD', 'Anxiety / Depression', 'Autoimmune Disease',
    'Metabolic Syndrome', 'Sleep Apnea', 'Chronic Fatigue',
];

const DIET_OPTIONS = [
    // Protein avoidances
    'No Beef', 'No Pork', 'No Lamb', 'No Poultry', 'No Seafood', 'No Red Meat',
    // Standard
    'Vegetarian', 'Vegan', 'Pescatarian', 'Flexitarian',
    // Indian / Cultural
    'Hindu (No Beef)', 'Jain', 'Sattvic (No Onion & Garlic)', 'Brahmin',
    'No Root Vegetables', 'No Underground Vegetables',
    // Religious
    'Halal', 'Kosher',
    // Dietary styles
    'Keto', 'Paleo', 'Whole30', 'Low-Carb', 'Low-Fat', 'Low-Sodium',
    'High-Protein', 'Raw Food', 'Gluten-Free', 'Dairy-Free', 'Sugar-Free',
    'Low-FODMAP', 'Mediterranean', 'DASH Diet', 'Macrobiotic', 'Carnivore',
    'Nut-Free', 'Egg-Free', 'Soy-Free',
];

const CUISINE_OPTIONS = ['American', 'Italian', 'Mexican'];

const ALL_INGREDIENTS = [
    // Proteins – Meat & Poultry
    'Chicken', 'Beef', 'Pork', 'Lamb', 'Turkey', 'Duck', 'Veal', 'Bison',
    'Venison', 'Rabbit', 'Bacon', 'Ham', 'Sausage', 'Hot Dogs', 'Pepperoni',
    'Prosciutto', 'Salami', 'Bologna', 'Chorizo', 'Bratwurst',
    // Seafood
    'Salmon', 'Tuna', 'Tilapia', 'Cod', 'Halibut', 'Mahi-Mahi', 'Catfish',
    'Trout', 'Sardines', 'Anchovies', 'Shrimp', 'Crab', 'Lobster', 'Clams',
    'Oysters', 'Mussels', 'Scallops', 'Squid / Calamari', 'Octopus', 'Herring',
    'Mackerel', 'Snapper', 'Sea Bass', 'Eel',
    // Plant proteins
    'Tofu', 'Tempeh', 'Seitan', 'Eggs', 'Lentils', 'Chickpeas', 'Black Beans',
    'Kidney Beans', 'White Beans', 'Pinto Beans', 'Navy Beans', 'Edamame',
    'Split Peas', 'Black-Eyed Peas', 'Mung Beans', 'Adzuki Beans', 'Fava Beans',
    // Dairy
    'Milk', 'Cheese', 'Butter', 'Heavy Cream', 'Yogurt', 'Greek Yogurt',
    'Sour Cream', 'Cream Cheese', 'Cottage Cheese', 'Mozzarella', 'Cheddar',
    'Parmesan', 'Feta', 'Brie', 'Gouda', 'Ricotta', 'Ghee', 'Whey Protein',
    'Ice Cream', 'Kefir', 'Buttermilk', 'Condensed Milk', 'Evaporated Milk',
    'Half and Half', 'Paneer',
    // Grains
    'Wheat', 'White Rice', 'Brown Rice', 'Pasta', 'Bread', 'Oats', 'Barley',
    'Quinoa', 'Corn', 'Flour', 'Cornmeal', 'Rye', 'Spelt', 'Farro', 'Millet',
    'Buckwheat', 'Couscous', 'Bulgur', 'Polenta', 'Tortillas', 'Pita Bread',
    'Naan', 'Sourdough', 'Bagel', 'Crackers', 'Cereal', 'Granola', 'Breadcrumbs',
    // Vegetables
    'Onion', 'Garlic', 'Tomato', 'Potato', 'Sweet Potato', 'Carrot', 'Broccoli',
    'Cauliflower', 'Spinach', 'Kale', 'Lettuce', 'Cucumber', 'Bell Pepper',
    'Zucchini', 'Eggplant', 'Mushroom', 'Celery', 'Asparagus', 'Green Beans',
    'Peas', 'Cabbage', 'Brussels Sprouts', 'Beet', 'Radish', 'Artichoke',
    'Leek', 'Fennel', 'Turnip', 'Parsnip', 'Bok Choy', 'Swiss Chard', 'Arugula',
    'Shallot', 'Scallion', 'Ginger', 'Turmeric Root', 'Jalapeño', 'Serrano Pepper',
    'Habanero', 'Butternut Squash', 'Acorn Squash', 'Spaghetti Squash', 'Pumpkin',
    'Yam', 'Taro', 'Lotus Root', 'Water Chestnuts', 'Bamboo Shoots', 'Bean Sprouts',
    'Snap Peas', 'Okra', 'Collard Greens', 'Mustard Greens', 'Watercress',
    'Endive', 'Radicchio', 'Jicama', 'Kohlrabi', 'Rutabaga', 'Celeriac',
    'Broccoli Rabe', 'Dandelion Greens', 'Bitter Melon', 'Drumstick (Moringa)',
    'Raw Banana', 'Plantain', 'Cassava', 'Breadfruit',
    // Fruits
    'Apple', 'Banana', 'Orange', 'Strawberry', 'Blueberry', 'Raspberry', 'Blackberry',
    'Grape', 'Watermelon', 'Mango', 'Pineapple', 'Peach', 'Pear', 'Cherry', 'Plum',
    'Kiwi', 'Avocado', 'Lemon', 'Lime', 'Grapefruit', 'Coconut', 'Pomegranate',
    'Fig', 'Date', 'Papaya', 'Guava', 'Passion Fruit', 'Dragonfruit', 'Jackfruit',
    'Persimmon', 'Lychee', 'Starfruit', 'Tamarind', 'Cantaloupe', 'Honeydew',
    'Apricot', 'Nectarine', 'Tangerine', 'Clementine', 'Pomelo', 'Longan',
    'Rambutan', 'Mangosteen', 'Durian',
    // Nuts & Seeds
    'Peanuts', 'Almonds', 'Cashews', 'Walnuts', 'Pecans', 'Pistachios',
    'Macadamia Nuts', 'Brazil Nuts', 'Hazelnuts', 'Pine Nuts', 'Sunflower Seeds',
    'Pumpkin Seeds', 'Sesame Seeds', 'Chia Seeds', 'Flaxseeds', 'Hemp Seeds',
    'Poppy Seeds', 'Sacha Inchi', 'Watermelon Seeds',
    // Condiments & Sauces
    'Soy Sauce', 'Fish Sauce', 'Oyster Sauce', 'Worcestershire Sauce', 'Hot Sauce',
    'Ketchup', 'Mustard', 'Mayonnaise', 'Honey', 'Maple Syrup', 'Tahini',
    'Peanut Butter', 'Almond Butter', 'Hoisin Sauce', 'Teriyaki Sauce', 'Sriracha',
    'Miso Paste', 'Gochujang', 'Harissa', 'Pesto', 'Tomato Sauce', 'Alfredo Sauce',
    'Coconut Aminos', 'Tamari', 'Chili Oil', 'Sambal', 'Doenjang',
    // Oils & Fats
    'Olive Oil', 'Vegetable Oil', 'Coconut Oil', 'Avocado Oil', 'Sesame Oil',
    'Canola Oil', 'Palm Oil', 'Lard', 'Tallow', 'Shortening',
    // Sweeteners
    'Sugar', 'Brown Sugar', 'Agave', 'Stevia', 'Corn Syrup', 'Molasses',
    'High-Fructose Corn Syrup', 'Xylitol', 'Erythritol', 'Jaggery',
    // Other
    'Alcohol', 'Beer', 'Wine', 'Caffeine', 'Coffee', 'Chocolate', 'Cocoa',
    'Gelatin', 'Asafoetida (Hing)', 'MSG', 'Carrageenan', 'Artificial Colors',
    'Artificial Flavors', 'Artificial Sweeteners', 'Preservatives',
].sort();

// ── Chip group component ─────────────────────────────────────────────────────

const ChipGroup = ({
    options,
    selected,
    onToggle,
    onCustomPress,
}: {
    options: string[];
    selected: string[];
    onToggle: (val: string) => void;
    onCustomPress?: () => void;
}) => (
    <View style={styles.chipWrap}>
        {options.map(opt => (
            <TouchableOpacity
                key={opt}
                style={[styles.chip, selected.includes(opt) && styles.chipOn]}
                onPress={() => onToggle(opt)}
            >
                <Text style={[styles.chipText, selected.includes(opt) && styles.chipTextOn]}>
                    {opt}
                </Text>
            </TouchableOpacity>
        ))}
        {onCustomPress && (
            <TouchableOpacity style={styles.chipCustom} onPress={onCustomPress}>
                <Ionicons name="add-circle-outline" size={13} color="#ee7422" />
                <Text style={styles.chipCustomText}> Custom</Text>
            </TouchableOpacity>
        )}
    </View>
);

// ── Radio button (TDEE calc) ─────────────────────────────────────────────────

const CustomRadioButton = ({ label, selected, onSelect }: { label: string; selected: boolean; onSelect: () => void }) => (
    <TouchableOpacity style={styles.radioContainer} onPress={onSelect}>
        <View style={[styles.radioButton, selected && styles.radioButtonSelected]}>
            {selected && <View style={styles.radioButtonInner} />}
        </View>
        <Text style={styles.radioLabel}>{label}</Text>
    </TouchableOpacity>
);

// ── Main screen ──────────────────────────────────────────────────────────────

export default function SearchScreen() {
    // Location + shopping time are collected on the previous (/location) screen and
    // passed in as params; prewarm has already started on the backend by now.
    const initial = useLocalSearchParams<{ location?: string; time?: string }>();
    // 5s gate overlay on mount — fake progress that hides the backend prewarm.
    const [gateVisible, setGateVisible] = useState(true);
    const [budget, setBudget] = useState('150');
    const [time, setTime] = useState(typeof initial.time === 'string' ? initial.time : '3');
    const [location, setLocation] = useState(typeof initial.location === 'string' ? initial.location : '');

    const [allergens, setAllergens] = useState<string[]>([]);
    const [healthConditions, setHealthConditions] = useState<string[]>([]);
    const [dietaryRestrictions, setDietaryRestrictions] = useState<string[]>([]);
    const [cuisines, setCuisines] = useState<string[]>([]);
    const [avoidIngredients, setAvoidIngredients] = useState<string[]>([]);

    const [experiment, setExperiment] = useState(true);
    const [cookTime, setCookTime] = useState('30-45 minutes');
    const [daysPlan, setDaysPlan] = useState('7');
    const [mealsPerDay, setMealsPerDay] = useState('3');
    const [householdSize, setHouseholdSize] = useState('1');
    const [calories, setCalories] = useState('2000');
    const [fridgeItems, setFridgeItems] = useState('');
    const [hasFridgeItems, setHasFridgeItems] = useState(false);
    const [hasCostcoCard, setHasCostcoCard] = useState(false);
    const [shoppingMode, setShoppingMode] = useState<'order_online' | 'delivery' | 'shop_in_person'>('shop_in_person');

    // TDEE calculator
    const [showCalculator, setShowCalculator] = useState(false);
    const [weight, setWeight] = useState('');
    const [heightFt, setHeightFt] = useState('');
    const [heightIn, setHeightIn] = useState('');
    const [age, setAge] = useState('');
    const [gender, setGender] = useState('M');
    const [activityLevel, setActivityLevel] = useState('2');
    const [goal, setGoal] = useState('2');

    // Ingredient avoid modal
    const [showIngModal, setShowIngModal] = useState(false);
    const [ingSearch, setIngSearch] = useState('');

    const router = useRouter();

    const filteredIngredients = useMemo(
        () => ALL_INGREDIENTS.filter(i => i.toLowerCase().includes(ingSearch.toLowerCase())),
        [ingSearch]
    );

    const toggle = (list: string[], setList: (v: string[]) => void) => (val: string) =>
        setList(list.includes(val) ? list.filter(x => x !== val) : [...list, val]);

    const toggleIngredient = (ing: string) =>
        setAvoidIngredients(prev => prev.includes(ing) ? prev.filter(x => x !== ing) : [...prev, ing]);

    const calculateTDEE = () => {
        try {
            const w = parseFloat(weight) * 0.453592;
            const h = ((parseInt(heightFt) * 12) + parseInt(heightIn)) * 2.54;
            const a = parseInt(age);
            let bmr = gender === 'M'
                ? (10 * w) + (6.25 * h) - (5 * a) + 5
                : (10 * w) + (6.25 * h) - (5 * a) - 161;
            const multipliers: Record<string, number> = { '1': 1.2, '2': 1.375, '3': 1.55, '4': 1.725 };
            let tdee = bmr * (multipliers[activityLevel] || 1.375);
            if (goal === '1') tdee -= 500;
            else if (goal === '3') tdee += 500;
            setCalories(Math.max(1200, Math.round(tdee)).toString());
            setShowCalculator(false);
        } catch {
            alert('Please fill in all calorie calculator fields correctly.');
        }
    };

    const handleSearch = () => {
        if (!budget && !time && !location) {
            alert('Please enter at least one of: Location, Budget, or Time.');
            return;
        }
        const params = {
            budget,
            time,
            location,
            dietary_restrictions: dietaryRestrictions.join(', '),
            cuisines: cuisines.join(', '),
            allergens: allergens.join(', '),
            avoid_ingredients: avoidIngredients.join(', '),
            experiment: experiment ? 'true' : 'false',
            cook_time: cookTime,
            days: daysPlan,
            meals_per_day: mealsPerDay,
            household_size: householdSize,
            calories,
            fridge_items: hasFridgeItems ? fridgeItems : '',
            health_issues: healthConditions.join(', '),
            has_costco_card: hasCostcoCard ? 'true' : 'false',
            shopping_mode: shoppingMode,
        };
        console.log('DEBUG: Navigating from Search with params:', params);
        router.push({ pathname: '/results', params });
    };

    return (
        <>
            {/* ── Ingredient avoid modal ── */}
            <Modal visible={showIngModal} animationType="slide" onRequestClose={() => setShowIngModal(false)}>
                <SafeAreaView style={styles.modalContainer}>
                    <View style={styles.modalHeader}>
                        <Text style={styles.modalTitle}>Avoid Specific Ingredients</Text>
                        <TouchableOpacity onPress={() => { setShowIngModal(false); setIngSearch(''); }}>
                            <Text style={styles.modalDone}>Done</Text>
                        </TouchableOpacity>
                    </View>

                    <View style={styles.modalSearchRow}>
                        <Ionicons name="search-outline" size={18} color="#9CA3AF" />
                        <TextInput
                            style={styles.modalSearchInput}
                            placeholder="Search ingredients..."
                            placeholderTextColor="#9CA3AF"
                            value={ingSearch}
                            onChangeText={setIngSearch}
                            autoFocus
                        />
                        {ingSearch.length > 0 && (
                            <TouchableOpacity onPress={() => setIngSearch('')}>
                                <Ionicons name="close-circle" size={18} color="#9CA3AF" />
                            </TouchableOpacity>
                        )}
                    </View>

                    {avoidIngredients.length > 0 && (
                        <ScrollView
                            horizontal
                            showsHorizontalScrollIndicator={false}
                            contentContainerStyle={styles.modalSelectedRow}
                        >
                            {avoidIngredients.map(ing => (
                                <TouchableOpacity
                                    key={ing}
                                    style={styles.chipOn}
                                    onPress={() => toggleIngredient(ing)}
                                >
                                    <Text style={styles.chipTextOn}>{ing} ×</Text>
                                </TouchableOpacity>
                            ))}
                        </ScrollView>
                    )}

                    <FlatList
                        data={filteredIngredients}
                        keyExtractor={item => item}
                        keyboardShouldPersistTaps="handled"
                        renderItem={({ item }) => {
                            const on = avoidIngredients.includes(item);
                            return (
                                <TouchableOpacity style={styles.ingRow} onPress={() => toggleIngredient(item)}>
                                    <Text style={[styles.ingText, on && styles.ingTextOn]}>{item}</Text>
                                    {on && <Ionicons name="checkmark-circle" size={20} color="#ee7422" />}
                                </TouchableOpacity>
                            );
                        }}
                    />
                </SafeAreaView>
            </Modal>

            {/* ── Main form ── */}
            <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
                <View style={{ flex: 1, backgroundColor: '#F9F9F9' }}>
                    <Stack.Screen options={{ headerShown: false }} />
                    <TopBanner />
                    <ScrollView contentContainerStyle={styles.page} showsVerticalScrollIndicator={false}>

                        <View style={styles.sectionHead}>
                            <Logo size={80} />
                            <View style={{ height: 8 }} />
                            <Text style={styles.header}>Plan Details</Text>
                        </View>

                        {/* Shopping Mode */}
                        <View style={styles.section}>
                            <View style={styles.card}>
                                <Text style={styles.label}>How would you like to shop?</Text>
                                <View style={styles.modeRow}>
                                    {([
                                        { key: 'order_online', icon: 'basket-outline', label: 'Order Online', sub: 'Pick up' },
                                        { key: 'delivery', icon: 'car-outline', label: 'Delivery', sub: 'At home' },
                                        { key: 'shop_in_person', icon: 'storefront-outline', label: 'Shop', sub: 'In person' },
                                    ] as const).map(({ key, icon, label, sub }) => (
                                        <TouchableOpacity
                                            key={key}
                                            style={[styles.modeTile, shoppingMode === key && styles.modeTileSelected]}
                                            onPress={() => setShoppingMode(key)}
                                        >
                                            <Ionicons name={icon} size={24} color={shoppingMode === key ? '#ee7422' : '#9CA3AF'} />
                                            <Text style={[styles.modeTileLabel, shoppingMode === key && styles.modeTileLabelSelected]}>{label}</Text>
                                            <Text style={styles.modeTileSub}>{sub}</Text>
                                        </TouchableOpacity>
                                    ))}
                                </View>
                            </View>
                        </View>

                        {/* Budget (location + shopping time are collected on /location) */}
                        <View style={styles.section}>
                            <View style={styles.card}>
                                <Text style={styles.label}>Weekly Budget ($)</Text>
                                <View style={styles.inputRow}>
                                    <Ionicons name="cash-outline" size={18} color="#9CA3AF" />
                                    <TextInput placeholder="150" placeholderTextColor="#9CA3AF" style={styles.iconInput} keyboardType="numeric" value={budget} onChangeText={setBudget} />
                                </View>
                            </View>
                        </View>

                        {/* Allergens */}
                        <View style={styles.section}>
                            <View style={styles.card}>
                                <Text style={styles.label}>Allergens</Text>
                                <ChipGroup
                                    options={ALLERGEN_OPTIONS}
                                    selected={allergens}
                                    onToggle={toggle(allergens, setAllergens)}
                                    onCustomPress={() => setShowIngModal(true)}
                                />
                            </View>
                        </View>

                        {/* Dietary Restrictions */}
                        <View style={styles.section}>
                            <View style={styles.card}>
                                <Text style={styles.label}>Dietary Restrictions</Text>
                                <ChipGroup
                                    options={DIET_OPTIONS}
                                    selected={dietaryRestrictions}
                                    onToggle={toggle(dietaryRestrictions, setDietaryRestrictions)}
                                    onCustomPress={() => setShowIngModal(true)}
                                />
                            </View>
                        </View>

                        {/* Health Conditions */}
                        <View style={styles.section}>
                            <View style={styles.card}>
                                <Text style={styles.label}>Health Conditions</Text>
                                <ChipGroup
                                    options={HEALTH_OPTIONS}
                                    selected={healthConditions}
                                    onToggle={toggle(healthConditions, setHealthConditions)}
                                />
                            </View>
                        </View>

                        {/* Cuisines */}
                        <View style={styles.section}>
                            <View style={styles.card}>
                                <Text style={styles.label}>Preferred Cuisine</Text>
                                <ChipGroup
                                    options={CUISINE_OPTIONS}
                                    selected={cuisines}
                                    onToggle={toggle(cuisines, setCuisines)}
                                />
                            </View>
                        </View>

                        {/* Planning Details */}
                        <View style={styles.section}>
                            <View style={styles.card}>
                                <View style={styles.row}>
                                    <View style={{ flex: 1, marginRight: 10 }}>
                                        <Text style={styles.label}>Days</Text>
                                        <View style={styles.inputRow}>
                                            <Ionicons name="calendar-outline" size={18} color="#9CA3AF" />
                                            <TextInput placeholder="7" placeholderTextColor="#9CA3AF" style={styles.iconInput} keyboardType="numeric" value={daysPlan} onChangeText={setDaysPlan} />
                                        </View>
                                    </View>
                                    <View style={{ flex: 1 }}>
                                        <Text style={styles.label}>Meals/Day</Text>
                                        <View style={styles.inputRow}>
                                            <Ionicons name="fast-food-outline" size={18} color="#9CA3AF" />
                                            <TextInput placeholder="3" placeholderTextColor="#9CA3AF" style={styles.iconInput} keyboardType="numeric" value={mealsPerDay} onChangeText={setMealsPerDay} />
                                        </View>
                                    </View>
                                </View>

                                <View style={{ marginTop: 16 }}>
                                    <Text style={styles.label}>People Cooking For</Text>
                                    <View style={styles.inputRow}>
                                        <Ionicons name="people-outline" size={18} color="#9CA3AF" />
                                        <TextInput placeholder="1" placeholderTextColor="#9CA3AF" style={styles.iconInput} keyboardType="numeric" value={householdSize} onChangeText={setHouseholdSize} />
                                    </View>
                                </View>

                                <View style={{ marginTop: 16 }}>
                                    <Text style={styles.label}>Max Cook Time</Text>
                                    <View style={styles.inputRow}>
                                        <Ionicons name="alarm-outline" size={18} color="#9CA3AF" />
                                        <TextInput placeholder="30-45 minutes" placeholderTextColor="#9CA3AF" style={styles.iconInput} value={cookTime} onChangeText={setCookTime} />
                                    </View>
                                </View>

                                <View style={[styles.switchGroup, { marginTop: 16 }]}>
                                    <Text style={styles.label}>Explore New Recipes?</Text>
                                    <Switch value={experiment} onValueChange={setExperiment} trackColor={{ false: '#CBD5E1', true: '#ee7422' }} thumbColor="#FFFFFF" />
                                </View>

                                <View style={[styles.switchGroup, { marginTop: 16 }]}>
                                    <Text style={styles.label}>Any ingredients at home?</Text>
                                    <Switch value={hasFridgeItems} onValueChange={setHasFridgeItems} trackColor={{ false: '#CBD5E1', true: '#ee7422' }} thumbColor="#FFFFFF" />
                                </View>

                                {hasFridgeItems && (
                                    <View style={{ marginTop: 16 }}>
                                        <Text style={styles.label}>Enter items (comma separated)</Text>
                                        <View style={styles.inputRow}>
                                            <Ionicons name="leaf-outline" size={18} color="#9CA3AF" />
                                            <TextInput placeholder="e.g. Eggs, Onion, Milk..." placeholderTextColor="#9CA3AF" style={styles.iconInput} multiline value={fridgeItems} onChangeText={setFridgeItems} />
                                        </View>
                                    </View>
                                )}

                                <View style={[styles.switchGroup, { marginTop: 16 }]}>
                                    <Text style={styles.label}>Do you have a Costco card?</Text>
                                    <Switch value={hasCostcoCard} onValueChange={setHasCostcoCard} trackColor={{ false: '#CBD5E1', true: '#ee7422' }} thumbColor="#FFFFFF" />
                                </View>
                            </View>
                        </View>

                        {/* Calories */}
                        <View style={styles.section}>
                            <View style={styles.card}>
                                <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                                    <Text style={styles.label}>Daily Calorie Target</Text>
                                    <TouchableOpacity onPress={() => setShowCalculator(!showCalculator)}>
                                        <Text style={styles.linkText}>{showCalculator ? 'Hide Calc' : 'Calculator'}</Text>
                                    </TouchableOpacity>
                                </View>
                                <View style={styles.inputRow}>
                                    <Ionicons name="flame-outline" size={18} color="#9CA3AF" />
                                    <TextInput placeholder="2000" placeholderTextColor="#9CA3AF" style={styles.iconInput} keyboardType="numeric" value={calories} onChangeText={setCalories} />
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

                        <GradientButton title="Generate Plan →" onPress={handleSearch} />

                    </ScrollView>
                </View>
            </KeyboardAvoidingView>

            {gateVisible && (
                <LoadingGate durationMs={5000} onDone={() => setGateVisible(false)} />
            )}
        </>
    );
}

const styles = StyleSheet.create({
    page: { backgroundColor: '#F9F9F9', padding: 20, paddingTop: 20, flexGrow: 1 },
    sectionHead: { marginBottom: 32, alignItems: 'center' },
    header: { fontSize: 28, fontWeight: '700', color: '#1A1A1A', fontFamily: 'Garamond-Bold', marginTop: 16 },
    section: { marginBottom: 16 },
    card: {
        backgroundColor: '#FFFFFF', borderRadius: 18, padding: 18, marginBottom: 8,
        borderWidth: 1, borderColor: '#1A1A1A',
        shadowColor: '#000', shadowOpacity: 0.05, shadowRadius: 12, shadowOffset: { width: 0, height: 6 },
        elevation: 4,
    },
    label: { fontSize: 14, fontWeight: '600', color: '#6B7280', marginBottom: 8 },
    inputRow: { flexDirection: 'row', alignItems: 'center', borderRadius: 12, paddingHorizontal: 12, backgroundColor: '#F9F9F9' },
    iconInput: { flex: 1, marginLeft: 10, paddingVertical: 14, fontSize: 16, color: '#1A1A1A' },
    row: { flexDirection: 'row', gap: 14 },
    half: { flex: 1 },
    switchGroup: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
    linkText: { color: '#ee7422', fontWeight: '600', fontSize: 12, textDecorationLine: 'underline' },

    // Chips
    chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
    chip: {
        paddingHorizontal: 12, paddingVertical: 7, borderRadius: 20,
        borderWidth: 1.5, borderColor: '#D1D5DB', backgroundColor: '#F9F9F9',
    },
    chipOn: {
        paddingHorizontal: 12, paddingVertical: 7, borderRadius: 20,
        borderWidth: 1.5, borderColor: '#ee7422', backgroundColor: '#FFF5E6',
    },
    chipText: { fontSize: 13, color: '#6B7280', fontWeight: '500' },
    chipTextOn: { fontSize: 13, color: '#ee7422', fontWeight: '600' },
    chipCustom: {
        flexDirection: 'row', alignItems: 'center',
        paddingHorizontal: 12, paddingVertical: 7, borderRadius: 20,
        borderWidth: 1.5, borderColor: '#ee7422', backgroundColor: '#FFFBF7',
    },
    chipCustomText: { fontSize: 13, color: '#ee7422', fontWeight: '600' },

    // Ingredient modal
    modalContainer: { flex: 1, backgroundColor: '#F9F9F9' },
    modalHeader: {
        flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
        paddingHorizontal: 20, paddingVertical: 16,
        borderBottomWidth: 1, borderBottomColor: '#E5E7EB', backgroundColor: '#FFFFFF',
    },
    modalTitle: { fontSize: 18, fontWeight: '700', color: '#1A1A1A', fontFamily: 'Garamond-Bold' },
    modalDone: { fontSize: 16, fontWeight: '600', color: '#ee7422' },
    modalSearchRow: {
        flexDirection: 'row', alignItems: 'center',
        margin: 16, paddingHorizontal: 14, paddingVertical: 10,
        backgroundColor: '#FFFFFF', borderRadius: 12, borderWidth: 1, borderColor: '#E5E7EB',
    },
    modalSearchInput: { flex: 1, marginLeft: 8, fontSize: 15, color: '#1A1A1A' },
    modalSelectedRow: { paddingHorizontal: 16, paddingBottom: 12, gap: 6 },
    ingRow: {
        flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
        paddingHorizontal: 20, paddingVertical: 14,
        borderBottomWidth: 1, borderBottomColor: '#F3F4F6', backgroundColor: '#FFFFFF',
    },
    ingText: { fontSize: 15, color: '#374151' },
    ingTextOn: { color: '#ee7422', fontWeight: '600' },

    // Calculator
    calculatorSection: { marginTop: 16, paddingTop: 16, borderTopWidth: 1, borderTopColor: '#E5E7EB' },
    sectionTitle: { fontSize: 16, fontWeight: 'bold', color: '#1A1A1A', marginBottom: 12 },
    labelSmall: { fontSize: 12, fontWeight: '600', color: '#6B7280', marginBottom: 4 },
    calcInput: { backgroundColor: '#F9F9F9', borderRadius: 8, height: 40, paddingHorizontal: 10, fontSize: 14 },
    calcButton: { backgroundColor: '#ee7422', height: 44, borderRadius: 10, justifyContent: 'center', alignItems: 'center', marginTop: 12 },
    calcButtonText: { color: '#FFF', fontSize: 14, fontWeight: 'bold' },

    // Radio
    radioContainer: { flexDirection: 'row', alignItems: 'center', marginRight: 16, marginBottom: 8 },
    radioButton: { height: 20, width: 20, borderRadius: 10, borderWidth: 2, borderColor: '#D1D5DB', alignItems: 'center', justifyContent: 'center', marginRight: 8 },
    radioButtonSelected: { borderColor: '#ee7422' },
    radioButtonInner: { height: 10, width: 10, borderRadius: 5, backgroundColor: '#ee7422' },
    radioLabel: { fontSize: 14, color: '#4B5563' },

    // Shopping mode
    modeRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
    modeTile: { flex: 1, alignItems: 'center', paddingVertical: 16, paddingHorizontal: 12, borderRadius: 12, backgroundColor: '#F9F9F9', borderWidth: 2, borderColor: '#E5E7EB' },
    modeTileSelected: { borderColor: '#ee7422', backgroundColor: '#FFF5E6' },
    modeTileLabel: { fontSize: 13, fontWeight: '600', color: '#6B7280', marginTop: 8, textAlign: 'center' },
    modeTileLabelSelected: { color: '#ee7422' },
    modeTileSub: { fontSize: 11, color: '#9CA3AF', marginTop: 2 },
});
