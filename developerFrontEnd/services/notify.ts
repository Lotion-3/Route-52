import { Alert, Platform } from 'react-native';

/**
 * Show a message on every platform.
 *
 * The two obvious calls each only work on half the targets:
 *   - `alert(...)`      is a browser global; undefined on iOS/Android, so the
 *                       message silently never appears.
 *   - `Alert.alert(...)` is a no-op on react-native-web.
 *
 * Screens were mixing both, so some validation errors were invisible depending
 * on where the app was running. Use this instead.
 */
export const notify = (title: string, message?: string): void => {
    const body = message ?? title;
    if (Platform.OS === 'web') {
        // eslint-disable-next-line no-alert
        if (typeof window !== 'undefined' && typeof window.alert === 'function') {
            window.alert(message ? `${title}\n\n${message}` : title);
        } else {
            console.warn(`[notify] ${title}: ${body}`);
        }
        return;
    }
    Alert.alert(title, message);
};

/**
 * Confirm-style message with an acknowledgement callback that fires on both
 * web and native (native waits for the OK press; web resolves immediately
 * after the modal is dismissed).
 */
export const notifyThen = (title: string, message: string, onDone: () => void): void => {
    if (Platform.OS === 'web') {
        notify(title, message);
        onDone();
        return;
    }
    Alert.alert(title, message, [{ text: 'OK', onPress: onDone }]);
};
