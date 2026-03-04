import React from "react";
import { StyleSheet, View, Text, TouchableOpacity } from "react-native";
import { useRouter } from "expo-router";

export default function TopBanner() {
    const router = useRouter();

    return (
        <View style={styles.header}>
            <TouchableOpacity style={styles.back} onPress={() => router.back()}>
                <Text style={styles.backText}>←</Text>
            </TouchableOpacity>

            <Text style={styles.title}>New Meal Plan</Text>
        </View>
    );
}

const styles = StyleSheet.create({
    header: {
        height: 56,
        backgroundColor: "#3B5DA1", // Route 52 blue
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: 16,
        borderBottomWidth: 1,
        borderBottomColor: "#3B5DA1",
    },
    back: {
        paddingRight: 12,
        paddingVertical: 6,
    },
    backText: {
        fontSize: 18,
        color: "#FFFFFF",
    },
    title: {
        fontSize: 16,
        fontWeight: "700",
        color: "#FFFFFF",
    },
});
