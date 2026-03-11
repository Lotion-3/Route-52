import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import 'react-native-reanimated';
import { StyleSheet, Text, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

import { useColorScheme } from '@/hooks/use-color-scheme';
import { Colors } from '@/constants/theme';

import { useFonts, EBGaramond_400Regular, EBGaramond_700Bold } from '@expo-google-fonts/eb-garamond';

// FEATURE FLAG: Set to false to disable backend status indicator
const ENABLE_BACKEND_STATUS = true;

// Prevent the splash screen from auto-hiding before asset loading is complete.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const [backendReady, setBackendReady] = useState<boolean | null>(null);

  const [loaded] = useFonts({
    'Garamond-Regular': EBGaramond_400Regular,
    'Garamond-Bold': EBGaramond_700Bold,
  });

  // Backend health check & wake-up nudge
  useEffect(() => {
    if (!ENABLE_BACKEND_STATUS) return;

    const isWeb = typeof window !== 'undefined';
    const isLocalhost = isWeb && (window.location.hostname.includes('localhost') || window.location.hostname.includes('127.0.0.1'));

    // Only check on production web, not localhost
    if (isWeb && !isLocalhost) {
      const checkBackend = async () => {
        try {
          const response = await fetch('https://route52.onrender.com/', { method: 'GET' });
          setBackendReady(response.ok);
        } catch {
          setBackendReady(false);
        }
      };

      checkBackend();
      // Re-check every 30 seconds to update status
      const interval = setInterval(checkBackend, 30000);
      return () => clearInterval(interval);
    }
  }, []);

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
    SplashScreen.hideAsync().catch(() => {});
  }

  return (
    <LinearGradient
      colors={['#FFFFFF', '#F3EDE4']} // white → soft beige
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={{ flex: 1 }}
    >
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
              backgroundColor: '#F3F0E9', // Warmer background
            }
          }}
        >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="search" options={{ title: 'New Meal Plan' }} />
          <Stack.Screen name="results" options={{ title: 'Your Plan' }} />
          <Stack.Screen name="+not-found" />
        </Stack>

        {/* Backend Status Indicator - REMOVE: Set ENABLE_BACKEND_STATUS to false to hide */}
        {ENABLE_BACKEND_STATUS && backendReady !== null && typeof window !== 'undefined' && (
          <View style={styles.statusIndicator}>
            <View style={[styles.statusDot, { backgroundColor: backendReady ? '#4CAF50' : '#FF9800' }]} />
            <Text style={styles.statusText}>
              {backendReady ? 'Ready' : 'Not Ready'}
            </Text>
          </View>
        )}

        <StatusBar style="auto" />
      </ThemeProvider>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  statusIndicator: {
    position: 'absolute',
    top: 16,
    right: 16,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.95)',
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
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#333',
  },
});