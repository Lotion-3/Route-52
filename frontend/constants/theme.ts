/**
 * Below are the colors that are used in the app. The colors are defined in the light and dark mode.
 * There are many other ways to style your app. For example, [Nativewind](https://www.nativewind.dev/), [Tamagui](https://tamagui.dev/), [unistyles](https://reactnativeunistyles.vercel.app), etc.
 */

import { Platform } from 'react-native';

const tintColorLight = '#0a7ea4';
const tintColorDark = '#fff';

const baseColors = {
  primary: '#ee7422',     // Brand Orange
  primaryDark: '#cc5f0f', // Darker Orange
  secondary: '#EE7422',
  accent: '#EE7422',
  error: '#EF4444',
  success: '#10B981',
};

export const Colors = {
  ...baseColors,
  text: '#1A1A1A',
  background: '#F9F9F9',
  tint: tintColorLight,
  icon: '#64748B',
  tabIconDefault: '#64748B',
  tabIconSelected: '#ee7422',
  card: '#FFFFFF',
  border: '#E2E8F0',
  textLight: '#6B7280',
  light: {
    ...baseColors,
    text: '#1A1A1A',
    background: '#F9F9F9',
    tint: tintColorLight,
    icon: '#64748B',
    tabIconDefault: '#64748B',
    tabIconSelected: '#ee7422',
    card: '#FFFFFF',
    border: '#E2E8F0',
    textLight: '#6B7280',
  },
  dark: {
    ...baseColors,
    text: '#1A1A1A',
    background: '#F9F9F9',
    tint: tintColorDark,
    icon: '#64748B',
    tabIconDefault: '#64748B',
    tabIconSelected: '#ee7422',
    card: '#FFFFFF',
    border: '#E2E8F0',
    textLight: '#6B7280',
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
