import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import 'react-native-reanimated';
import { StyleSheet, Text, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import MainLayout from '@/components/MainLayout';

import { useColorScheme } from '@/hooks/use-color-scheme';

import { useFonts, EBGaramond_400Regular, EBGaramond_700Bold } from '@expo-google-fonts/eb-garamond';
import { Fraunces_400Regular, Fraunces_700Bold } from '@expo-google-fonts/fraunces';
import { WorkSans_400Regular, WorkSans_600SemiBold, WorkSans_700Bold } from '@expo-google-fonts/work-sans';

// Prevent the splash screen from auto-hiding before asset loading is complete.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const colorScheme = useColorScheme();

  const [loaded] = useFonts({
    'Garamond-Regular': EBGaramond_400Regular,
    'Garamond-Bold': EBGaramond_700Bold,
    'Fraunces-Regular': Fraunces_400Regular,
    'Fraunces-Bold': Fraunces_700Bold,
    'WorkSans-Regular': WorkSans_400Regular,
    'WorkSans-SemiBold': WorkSans_600SemiBold,
    'WorkSans-Bold': WorkSans_700Bold,
  });

  useEffect(() => {
    if (loaded) {
      SplashScreen.hideAsync();
    }
  }, [loaded]);

  // On web, render even if fonts aren't loaded to avoid blank page
  const isWeb = typeof window !== 'undefined';
  if (!loaded && !isWeb) {
    return null;
  }

  if (!loaded && isWeb) {
    SplashScreen.hideAsync().catch(() => { });
  }

  return (
    <View style={{ flex: 1, position: 'relative' }}>
      <MainLayout>
        <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
          <Stack
            screenOptions={{
              headerStyle: {
                backgroundColor: '#3B5DA1', // Blue header
              },
              headerShadowVisible: false,
              headerTintColor: '#FFFFFF', // White tint for contrast
              headerTitleStyle: {
                fontWeight: 'bold',
              },
              contentStyle: {
                backgroundColor: '#FFF2E0', // Set background color to #FFF2E0
              }
            }}
          >
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="location" options={{ title: 'New Meal Plan' }} />
            <Stack.Screen name="search" options={{ title: 'Plan Details' }} />
            <Stack.Screen name="results" options={{ title: 'Your Plan' }} />
            <Stack.Screen name="+not-found" />
          </Stack>

          <StatusBar style="auto" />
        </ThemeProvider>
      </MainLayout>

      {/* Marks this running app as the static developer copy — see
          developerFrontEnd/README.md — so it's never mistaken for the real,
          backend-wired frontend/ while restyling. Delete this block (and the
          styles.demoBadge* entries below) once no longer needed. */}
      <View style={styles.demoBadge} pointerEvents="none">
        <View style={styles.demoBadgeDot} />
        <Text style={styles.demoBadgeText}>DEMO — static data</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  demoBadge: {
    position: 'absolute',
    top: 16,
    right: 16,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(26, 26, 26, 0.9)',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 20,
    zIndex: 1000,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 5,
  },
  demoBadgeDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
    backgroundColor: '#ee7422',
  },
  demoBadgeText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#FFFFFF',
  },
});