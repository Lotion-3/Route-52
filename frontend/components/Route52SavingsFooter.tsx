import React from "react";
import { StyleSheet, Text, View } from "react-native";

export type StoreTotal = {
    storeName: string; // e.g. "Costco", "Walmart", "Aldi"
    total: number;     // total cost for that store option
};

function formatMoney(n: number) {
    const safe = Math.max(0, n);
    return `$${safe.toFixed(2)}`;
}

function getCheapVsExpensive(stores: StoreTotal[]) {
    if (!stores || stores.length < 2) return null;

    const sorted = [...stores].sort((a, b) => a.total - b.total);
    const cheapest = sorted[0];
    const mostExpensive = sorted[sorted.length - 1];

    const savings = mostExpensive.total - cheapest.total;
    return { cheapest, mostExpensive, savings };
}

export default function Route52SavingsFooter({
    storeTotals,
    bestSplitLabel,
}: {
    storeTotals: StoreTotal[];
    bestSplitLabel?: string; // optional subtext
}) {
    const result = getCheapVsExpensive(storeTotals);

    if (!result) return null;

    const { mostExpensive, savings } = result;

    return (
        <View style={styles.footerWrap}>
            <View style={styles.footerBar}>
                <View style={styles.left}>
                    <View style={styles.badge}>
                        <Text style={styles.badgeText}>SAVE</Text>
                    </View>

                    <View style={styles.textBlock}>
                        <Text style={styles.headline} numberOfLines={2}>
                            You save {formatMoney(savings)} here versus{" "}
                            {mostExpensive.storeName}
                        </Text>

                        {!!bestSplitLabel && (
                            <Text style={styles.context} numberOfLines={1}>
                                Using optimized pricing & logic
                            </Text>
                        )}
                    </View>
                </View>

                <View style={styles.right}>
                    <Text style={styles.rightLabel}>Savings</Text>
                    <Text style={styles.rightValue}>{formatMoney(savings)}</Text>
                </View>
            </View>
        </View>
    );
}

const styles = StyleSheet.create({
    footerWrap: {
        marginTop: 10,
        paddingTop: 10,
        borderTopWidth: 1,
        borderTopColor: "#EEF2F7",
    },
    footerBar: {
        backgroundColor: "#EFECE5", // subtle warm contrast
        borderRadius: 14,
        paddingVertical: 10,
        paddingHorizontal: 12,
        borderWidth: 1,
        borderColor: "#E5E7EB",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
    },
    left: {
        flex: 1,
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        minWidth: 0,
    },
    badge: {
        paddingHorizontal: 10,
        paddingVertical: 6,
        borderRadius: 999,
        backgroundColor: "#3B5DA1", // Route 52 blue
    },
    badgeText: {
        color: "#FFFFFF",
        fontWeight: "900",
        fontSize: 11,
        letterSpacing: 0.4,
    },
    textBlock: {
        flex: 1,
        minWidth: 0,
    },
    headline: {
        fontSize: 14,
        fontWeight: "700",
        color: "#1F2937",
        flexShrink: 1,
    },
    context: {
        fontSize: 12,
        color: "#6B7280",
        marginTop: 2,
    },
    right: {
        alignItems: "flex-end",
    },
    rightLabel: {
        color: "#6B7280",
        fontSize: 11,
        fontWeight: "700",
    },
    rightValue: {
        marginTop: 1,
        color: "#111827",
        fontSize: 13,
        fontWeight: "900",
        fontVariant: ["tabular-nums"],
    },
});
