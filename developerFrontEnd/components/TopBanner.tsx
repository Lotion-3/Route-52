import React from "react";
import { StyleSheet, View, Text, TouchableOpacity, Platform } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

function ZigzagEdge({ color = '#b0db9d' }: { color?: string }) {
  if (Platform.OS !== 'web') return null;

  return React.createElement(
    'svg',
    {
      viewBox: '0 0 100 10',
      preserveAspectRatio: 'none',
      style: { width: '100%', height: '12px', display: 'block' },
    },
    React.createElement('polygon', {
      points: '0,0 5,10 10,0 15,10 20,0 25,10 30,0 35,10 40,0 45,10 50,0 55,10 60,0 65,10 70,0 75,10 80,0 85,10 90,0 95,10 100,0',
      fill: color,
    })
  );
}

export default function TopBanner() {
    const router = useRouter();

    return (
        <View style={{ width: '100%', position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10, backgroundColor: 'transparent' }}>
            <View style={styles.header}>
                {/* CSS background dot grid on Web */}
                {Platform.OS === 'web' && (
                  <View
                    style={{
                      position: 'absolute',
                      top: 0, left: 0, right: 0, bottom: 0,
                      backgroundImage: 'radial-gradient(rgba(74, 122, 58, 0.08) 12%, transparent 13%)',
                      backgroundSize: '16px 16px',
                      backgroundPosition: '8px 8px',
                    } as any}
                    pointerEvents="none"
                  />
                )}

                <View style={styles.contentRow}>
                    <TouchableOpacity style={styles.back} onPress={() => router.back()}>
                        <Ionicons name="arrow-back" size={24} color="#1A1A1A" />
                    </TouchableOpacity>
                    
                    <TouchableOpacity 
                        style={styles.homeGroup} 
                        onPress={() => router.replace('/')}
                        activeOpacity={0.7}
                    >
                        <Ionicons name="home" size={20} color="#1A1A1A" style={styles.homeIcon} />
                        <Text style={styles.title}>New Meal Plan</Text>
                    </TouchableOpacity>
                </View>

                {/* Perforation line */}
                <View style={[styles.perforationLine, Platform.OS === 'web' && {
                  backgroundImage: 'linear-gradient(to right, #FFF8F0 65%, transparent 65%)',
                  backgroundSize: '24px 2px',
                  backgroundRepeat: 'repeat-x',
                  borderStyle: 'none',
                  borderWidth: 0,
                  height: 2,
                } as any]} />

                {/* Ticket notches */}
                <View style={[styles.notch, { left: 16 }]} />
                <View style={[styles.notch, { right: 16 }]} />
            </View>
            <ZigzagEdge />
        </View>
    );
}

const styles = StyleSheet.create({
    header: {
        height: 64,
        backgroundColor: "#b0db9d",
        justifyContent: "center",
        width: '100%',
        position: 'relative',
    },
    contentRow: {
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: 16,
        zIndex: 2,
    },
    back: {
        paddingRight: 12,
        paddingVertical: 6,
    },
    homeGroup: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    homeIcon: {
        transform: [{ translateY: -1 }],
    },
    title: {
        fontSize: 18,
        fontWeight: "700",
        color: "#1A1A1A",
        fontFamily: 'Fraunces-Bold',
    },
    perforationLine: {
        position: 'absolute',
        bottom: 8,
        left: 0,
        right: 0,
        borderWidth: 1,
        borderColor: '#FFF8F0',
        borderStyle: 'dashed',
        height: 0,
    },
    notch: {
        position: 'absolute',
        top: '50%',
        marginTop: -10,
        width: 20,
        height: 20,
        borderRadius: 10,
        backgroundColor: '#FFF2E0',
        zIndex: 5,
    },
});
