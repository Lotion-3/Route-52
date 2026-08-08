import React from "react";
import {
    StyleSheet,
    Text,
    TouchableOpacity,
    View,
    Platform,
} from "react-native";

type DownloadFabProps = {
    onPress: () => void;
    label?: string;
};

export function DownloadFab({
    onPress,
    label = "Download",
}: DownloadFabProps) {
    return (
        <View pointerEvents="box-none" style={styles.container}>
            <TouchableOpacity
                activeOpacity={0.85}
                onPress={onPress}
                style={styles.button}
            >
                <Text style={styles.text}>{label}</Text>
            </TouchableOpacity>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        position: "absolute",
        right: 20,
        bottom: 24, // safe for most devices
        zIndex: 999, // Ensure it stays above other content
    },
    button: {
        backgroundColor: "#E8821E",
        paddingHorizontal: 24,
        paddingVertical: 14,
        borderRadius: 999,
        shadowColor: "#000",
        shadowOpacity: 0.2,
        shadowRadius: 10,
        shadowOffset: { width: 0, height: 6 },
        elevation: Platform.OS === "android" ? 8 : 0,
        flexDirection: 'row',
        alignItems: 'center',
    },
    text: {
        color: "#FFFFFF",
        fontWeight: "800",
        fontSize: 14,
        letterSpacing: 0.4,
        textTransform: "uppercase",
    },
});
