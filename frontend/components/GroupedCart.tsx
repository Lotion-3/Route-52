import React, { useMemo, useState } from "react";
import {
    SectionList,
    StyleSheet,
    Text,
    TouchableOpacity,
    View,
    ViewStyle,
} from "react-native";

export type CartItem = {
    id: string;
    name: string;
    qty: number;
    price: number; // total price for this line item (already multiplied by qty)
    category: "Produce" | "Dairy" | "Meat" | "Pantry" | "Frozen" | "Other";
};

type SectionData = {
    title: string;
    data: CartItem[];
    total: number; // category total
};

function formatMoney(n: number) {
    return `$${n.toFixed(2)}`;
}

function chunk<T>(arr: T[], size: number) {
    const out: T[][] = [];
    for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
    return out;
}

export default function GroupedCart({
    items,
    cardStyle,
    columns = 2,
}: {
    items: CartItem[];
    cardStyle?: ViewStyle;
    columns?: 2 | 3;
}) {
    const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

    const sections: SectionData[] = useMemo(() => {
        const map = new Map<string, CartItem[]>();
        for (const it of items) {
            const key = it.category ?? "Other";
            if (!map.has(key)) map.set(key, []);
            map.get(key)!.push(it);
        }

        const order = ["Produce", "Meat", "Dairy", "Pantry", "Frozen", "Other"];
        const titles = Array.from(map.keys()).sort(
            (a, b) => order.indexOf(a) - order.indexOf(b)
        );

        return titles.map((title) => {
            const data = map.get(title)!.sort((a, b) => a.name.localeCompare(b.name));
            const total = data.reduce((sum, it) => sum + it.price, 0);
            return { title, data, total };
        });
    }, [items]);

    return (
        <View style={[styles.card, cardStyle]}>
            <SectionList
                sections={sections}
                keyExtractor={(item) => item.id}
                stickySectionHeadersEnabled={false}
                scrollEnabled={false} // Disable inner scrolling as it will be inside another FlatList
                contentContainerStyle={styles.listContent}
                renderSectionHeader={({ section }) => {
                    const isCollapsed = collapsed[section.title] === true;
                    const count = section.data.length;

                    return (
                        <TouchableOpacity
                            activeOpacity={0.85}
                            onPress={() =>
                                setCollapsed((prev) => ({
                                    ...prev,
                                    [section.title]: !isCollapsed,
                                }))
                            }
                            style={styles.sectionHeader}
                        >
                            <View style={styles.sectionHeaderLeft}>
                                <Text style={styles.sectionTitle}>{section.title}</Text>
                                <View style={styles.countPill}>
                                    <Text style={styles.countText}>{count}</Text>
                                </View>
                            </View>

                            <View style={styles.sectionHeaderRight}>
                                <Text style={styles.sectionTotal}>{formatMoney(section.total)}</Text>
                                <Text style={styles.chevron}>{isCollapsed ? "▸" : "▾"}</Text>
                            </View>
                        </TouchableOpacity>
                    );
                }}
                renderSectionFooter={({ section }) => {
                    const isCollapsed = collapsed[section.title] === true;
                    if (isCollapsed) return null;

                    const rows = chunk(section.data, columns);

                    return (
                        <View style={styles.gridWrap}>
                            {rows.map((row, idx) => (
                                <View key={`${section.title}-row-${idx}`} style={styles.gridRow}>
                                    {row.map((it) => (
                                        <View key={it.id} style={styles.gridItem}>
                                            <View style={styles.itemTop}>
                                                <Text numberOfLines={1} style={styles.itemName}>
                                                    {it.name}
                                                </Text>
                                                <View style={styles.qtyPill}>
                                                    <Text style={styles.qtyText}>x{it.qty}</Text>
                                                </View>
                                            </View>

                                            <View style={styles.priceRow}>
                                                <View style={styles.priceCol}>
                                                    <Text style={styles.itemPrice}>{formatMoney(it.price)}</Text>
                                                </View>
                                            </View>
                                        </View>
                                    ))}

                                    {row.length < columns &&
                                        Array.from({ length: columns - row.length }).map((_, k) => (
                                            <View
                                                key={`${section.title}-spacer-${idx}-${k}`}
                                                style={[styles.gridItem, styles.gridItemSpacer]}
                                            />
                                        ))}
                                </View>
                            ))}
                        </View>
                    );
                }}
                renderItem={() => null}
            />
        </View>
    );
}

const PRICE_COL_WIDTH = 78;

const styles = StyleSheet.create({
    card: {
        backgroundColor: "#FFFFFF",
        borderRadius: 16,
        paddingVertical: 10,
        paddingHorizontal: 12,
        shadowColor: "#000",
        shadowOpacity: 0.06,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 8 },
        elevation: 3,
    },
    listContent: {
        paddingBottom: 8,
    },
    sectionHeader: {
        paddingVertical: 10,
        paddingHorizontal: 6,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
    },
    sectionHeaderLeft: {
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
    },
    sectionHeaderRight: {
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
    },
    sectionTitle: {
        fontSize: 14,
        fontWeight: "700",
        color: "#111827",
    },
    sectionTotal: {
        fontSize: 13,
        fontWeight: "800",
        color: "#111827",
        fontVariant: ["tabular-nums"],
        width: PRICE_COL_WIDTH,
        textAlign: "right",
    },
    countPill: {
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 999,
        backgroundColor: "#EEF2FF",
    },
    countText: {
        fontSize: 12,
        fontWeight: "700",
        color: "#374151",
    },
    chevron: {
        fontSize: 16,
        color: "#6B7280",
        paddingRight: 2,
    },
    gridWrap: {
        paddingHorizontal: 2,
        paddingBottom: 10,
    },
    gridRow: {
        flexDirection: "row",
        gap: 10,
        marginTop: 10,
    },
    gridItem: {
        flex: 1,
        backgroundColor: "#F9FAFB",
        borderRadius: 14,
        paddingVertical: 10,
        paddingHorizontal: 10,
        borderWidth: 1,
        borderColor: "#EEF2F7",
    },
    gridItemSpacer: {
        backgroundColor: "transparent",
        borderWidth: 0,
    },
    itemTop: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
    },
    itemName: {
        flex: 1,
        fontSize: 13,
        fontWeight: "600",
        color: "#374151",
    },
    qtyPill: {
        paddingHorizontal: 8,
        paddingVertical: 3,
        borderRadius: 999,
        backgroundColor: "#111827",
    },
    qtyText: {
        fontSize: 11,
        fontWeight: "800",
        color: "#FFFFFF",
    },
    priceRow: {
        marginTop: 10,
        flexDirection: "row",
        justifyContent: "flex-end",
    },
    priceCol: {
        width: PRICE_COL_WIDTH,
        alignItems: "flex-end",
    },
    itemPrice: {
        fontSize: 13,
        fontWeight: "800",
        color: "#111827",
        fontVariant: ["tabular-nums"],
    },
});
