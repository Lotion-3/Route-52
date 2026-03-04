/**
 * Below are the colors that are used in the app. The colors are defined in the light and dark mode.
 * There are many other ways to style your app. For example, [Nativewind](https://www.nativewind.dev/), [Tamagui](https://tamagui.dev/), [unistyles](https://reactnativeunistyles.vercel.app), etc.
 */

import { Platform } from 'react-native';

const tintColorLight = '#0a7ea4';
const tintColorDark = '#fff';

const baseColors = {
  primary: '#3B5DA1',     // Route 52 Blue
  primaryDark: '#2D477A', // Darker Blue
  secondary: '#EE7422',   // Route 52 Orange
  accent: '#EE7422',      // Using the same orange for accent
  error: '#EF4444',
  success: '#10B981',
};

export const Colors = {
  ...baseColors,
  text: '#1E293B',
  background: '#F3F0E9', // Deeper Warm Off-White
  tint: tintColorLight,
  icon: '#64748B',
  tabIconDefault: '#64748B',
  tabIconSelected: '#3B5DA1',
  card: '#FFFFFF',
  border: '#E2E8F0',
  textLight: '#64748B',
  light: {
    ...baseColors,
    text: '#1E293B',
    background: '#F3F0E9',
    tint: tintColorLight,
    icon: '#64748B',
    tabIconDefault: '#64748B',
    tabIconSelected: '#3B5DA1',
    card: '#FFFFFF',
    border: '#E2E8F0',
    textLight: '#64748B',
  },
  dark: {
    ...baseColors,
    text: '#1E293B',
    background: '#F3F0E9',
    tint: tintColorDark,
    icon: '#64748B',
    tabIconDefault: '#64748B',
    tabIconSelected: '#3B5DA1',
    card: '#FFFFFF',
    border: '#E2E8F0',
    textLight: '#64748B',
  },
};

export const Fonts = Platform.select({
  ios: {
    /** iOS `UIFontDescriptorSystemDesignDefault` */
    sans: 'system-ui',
    /** iOS `UIFontDescriptorSystemDesignSerif` */
    serif: 'ui-serif',
    /** iOS `UIFontDescriptorSystemDesignRounded` */
    rounded: 'ui-rounded',
    /** iOS `UIFontDescriptorSystemDesignMonospaced` */
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    serif: "Georgia, 'Times New Roman', serif",
    rounded: "'SF Pro Rounded', 'Hiragino Maru Gothic ProN', Meiryo, 'MS PGothic', sans-serif",
    mono: "SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
  },
});
