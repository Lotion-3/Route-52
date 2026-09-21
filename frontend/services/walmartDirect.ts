import { Platform } from 'react-native';

/**
 * EXPERIMENTAL (2026-09-20): price Walmart items by hitting walmart.com
 * directly from THIS device, using a cookie handed out by our backend
 * (GET /api/walmart/session — see server.py's walmart_client_session /
 * walmart_pricing.get_client_session). The hypothesis being tested: Render's
 * shared egress IP keeps getting rate-limited/banned by Walmart's WAF
 * because every request comes from one IP; spreading requests across real
 * users' own IPs might dodge that.
 *
 * Native-app only (Platform.OS !== 'web') — a browser page can't do this at
 * all: cross-origin `fetch` to walmart.com with `credentials: 'include'`
 * would need Walmart's own CORS policy to allow our origin and share its
 * cookies with it, which it doesn't. React Native's fetch isn't subject to
 * browser CORS, so this only works in a native (Expo Go / dev / built) app.
 *
 * This is a deliberately simplified port of walmart_pricing.py's HTTP path
 * (_fetch_items_http / _item_to_kroger_format / _price_one) — matching here
 * is "cheapest item whose name contains a query word" rather than the full
 * qty/unit purchase-optimization the backend does. Good enough to test
 * whether the request itself gets through; not a drop-in replacement for
 * the server's pricing yet.
 */

export const isWalmartDirectSupported = Platform.OS !== 'web';

const WALMART_SEARCH_URL = (q: string) =>
    `https://www.walmart.com/search?q=${encodeURIComponent(q)}&affinityOverride=default&ps=40`;
const WALMART_WARM_URL = 'https://www.walmart.com/';

const NEXT_DATA_RE = /<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/;
const EXPLICIT_BLOCK_MARKERS = ['px-captcha', 'blocked temporarily', 'access to this page has been denied'];

export interface WalmartSession {
    cookies: Record<string, string>;
    ua: string;
}

export interface WalmartDirectItem {
    name: string;
    brand: string;
    price: number;
    size: string;
    soldByWeight: boolean;
    itemId: string;
}

export class WalmartDirectBlocked extends Error {
    category: 'explicit' | 'soft' | 'transport';
    constructor(message: string, category: 'explicit' | 'soft' | 'transport') {
        super(message);
        this.category = category;
    }
}

// Reuse api.ts's already-resolved backend URL instead of a second copy of
// its resolution logic — a duplicated copy here previously fell back to the
// PRODUCTION Render URL whenever it disagreed with api.ts, which doesn't
// have this experimental endpoint deployed (silent 404s, "device" pricing
// tests were actually hitting prod, not the local backend api.ts used).
import { DEV_API_URL as API_BASE } from './api';

/** Fetch a cookie+UA from our backend to bootstrap the first request with —
 * see the module docstring above for why the server, not this device, mints it. */
export const fetchWalmartSession = async (): Promise<WalmartSession> => {
    const res = await fetch(`${API_BASE}/api/walmart/session`);
    if (!res.ok) {
        throw new Error(`No Walmart session available (${res.status}).`);
    }
    return res.json();
};

/** Fetch every cached cookie the backend currently knows about (local pool
 * file + Supabase pool), unvalidated — see testWalmartCookiePoolDirect,
 * which is what actually checks each one from this device. */
export const fetchWalmartSessionPool = async (): Promise<WalmartSession[]> => {
    const res = await fetch(`${API_BASE}/api/walmart/session_pool`);
    if (!res.ok) {
        throw new Error(`Couldn't fetch the cookie pool (${res.status}).`);
    }
    const data = await res.json();
    return Array.isArray(data?.sessions) ? data.sessions : [];
};

const cookieHeader = (cookies: Record<string, string>): string =>
    Object.entries(cookies).map(([k, v]) => `${k}=${v}`).join('; ');

/** Walk __NEXT_DATA__ to the search itemStacks[].items[] list — mirrors
 * walmart_pricing.py's _find_items. */
const findItems = (o: any): any[] => {
    if (o && typeof o === 'object' && !Array.isArray(o)) {
        if (Array.isArray(o.itemStacks)) {
            const items: any[] = [];
            for (const st of o.itemStacks) {
                if (st && Array.isArray(st.items)) items.push(...st.items);
            }
            if (items.length) return items;
        }
        for (const v of Object.values(o)) {
            const r = findItems(v);
            if (r.length) return r;
        }
    } else if (Array.isArray(o)) {
        for (const v of o) {
            const r = findItems(v);
            if (r.length) return r;
        }
    }
    return [];
};

const extractPriceNumber = (raw: unknown): number | null => {
    const m = String(raw ?? '').replace(/,/g, '').match(/(\d+(?:\.\d{1,2})?)/);
    if (!m) return null;
    const val = parseFloat(m[1]);
    return val >= 0.01 && val <= 500 ? val : null;
};

const priceFromLineprice = (priceInfo: any): number | null => {
    const raw = priceInfo?.linePrice || priceInfo?.linePriceDisplay || priceInfo?.itemPrice || '';
    const val = extractPriceNumber(raw);
    if (val !== null) return val;
    // Walmart migrated to this structure ~2026-07 (see walmart_pricing.py's
    // _price_from_lineprice) — flat fields come back empty; the real price
    // lives in priceDetails.priceLines[lineType=CURRENT_PRICE].values[key=PRICE].
    for (const line of priceInfo?.priceDetails?.priceLines ?? []) {
        if (line?.lineType !== 'CURRENT_PRICE') continue;
        for (const v of line?.values ?? []) {
            if (v?.key === 'PRICE') {
                const p = extractPriceNumber(v.value);
                if (p !== null) return p;
            }
        }
    }
    return null;
};

const toDirectItem = (item: any): WalmartDirectItem | null => {
    const name: string = item?.name || '';
    if (!name || item?.hasSellerBadge) return null; // skip marketplace sellers, same as backend
    const price = priceFromLineprice(item?.priceInfo ?? {});
    if (price === null) return null;
    return {
        name,
        brand: item?.brand || '',
        price,
        size: item?.priceInfo?.finalCostByWeight ? '1 lb' : '',
        soldByWeight: !!item?.priceInfo?.finalCostByWeight,
        itemId: String(item?.usItemId || item?.id || ''),
    };
};

/** One search over plain HTTP from THIS device, replaying the given cookie +
 * matching Chrome-like headers. Throws WalmartDirectBlocked on a WAF
 * challenge, same three categories as the backend's _Blocked. */
export const searchWalmartDirect = async (
    term: string,
    session: WalmartSession,
): Promise<WalmartDirectItem[]> => {
    let text: string;
    try {
        const res = await fetch(WALMART_SEARCH_URL(term), {
            headers: {
                accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'accept-language': 'en-US,en;q=0.9',
                referer: WALMART_WARM_URL,
                'user-agent': session.ua,
                cookie: cookieHeader(session.cookies),
            },
        });
        text = await res.text();
    } catch (e: any) {
        throw new WalmartDirectBlocked(`request failed: ${String(e?.message || e).slice(0, 80)}`, 'transport');
    }
    const lower = text.toLowerCase();
    if (EXPLICIT_BLOCK_MARKERS.some((m) => lower.includes(m))) {
        throw new WalmartDirectBlocked('px-captcha marker', 'explicit');
    }
    const m = NEXT_DATA_RE.exec(text);
    if (!m) {
        throw new WalmartDirectBlocked('no __NEXT_DATA__', 'soft');
    }
    let items: any[];
    try {
        items = findItems(JSON.parse(m[1]));
    } catch {
        return []; // parseable page, just no usable items
    }
    return items.map(toDirectItem).filter((x): x is WalmartDirectItem => x !== null);
};

/** Cheapest item whose name contains any query word — a deliberately simple
 * stand-in for the backend's qty/unit purchase-optimization matching. */
const bestMatch = (query: string, items: WalmartDirectItem[]): WalmartDirectItem | null => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const candidates = items.filter((it) =>
        words.some((w) => it.name.toLowerCase().includes(w)),
    );
    const pool = candidates.length ? candidates : items;
    if (!pool.length) return null;
    return pool.reduce((best, it) => (it.price < best.price ? it : best), pool[0]);
};

/** Price a whole ingredient list, one search per ingredient, sequentially
 * (a real shopper doesn't fire 50 concurrent requests — also keeps this
 * device-friendly). Returns {ingredientName: WalmartDirectItem}; ingredients
 * with no match/blocked search are simply left out. */
export const priceIngredientsWalmartDirect = async (
    ingredientNames: string[],
    session: WalmartSession,
    onProgress?: (done: number, total: number) => void,
): Promise<Record<string, WalmartDirectItem>> => {
    const out: Record<string, WalmartDirectItem> = {};
    for (let i = 0; i < ingredientNames.length; i++) {
        const name = ingredientNames[i];
        try {
            const items = await searchWalmartDirect(name, session);
            const match = bestMatch(name, items);
            if (match) out[name] = match;
        } catch (e) {
            console.log(`[walmartDirect] '${name}' failed:`, e);
        }
        onProgress?.(i + 1, ingredientNames.length);
    }
    return out;
};

export interface PoolTestResult {
    index: number;
    ok: boolean;
    itemCount: number;
    error?: string;
}

/** Walk the WHOLE cached cookie pool and try each one from THIS device with
 * one lightweight search — not full pricing per cookie, that'd be pool_size
 * × ingredient_count requests. Answers "how many of our cached cookies still
 * work when replayed from a real phone?" rather than "price my list." */
export const testWalmartCookiePoolDirect = async (
    onProgress?: (done: number, total: number) => void,
): Promise<{ total: number; alive: number; results: PoolTestResult[] }> => {
    const pool = await fetchWalmartSessionPool();
    const results: PoolTestResult[] = [];
    let alive = 0;
    for (let i = 0; i < pool.length; i++) {
        try {
            const items = await searchWalmartDirect('milk', pool[i]);
            const ok = items.length > 0;
            if (ok) alive++;
            results.push({ index: i, ok, itemCount: items.length });
        } catch (e: any) {
            results.push({ index: i, ok: false, itemCount: 0, error: String(e?.message || e).slice(0, 60) });
        }
        onProgress?.(i + 1, pool.length);
    }
    return { total: pool.length, alive, results };
};

export interface WorkingSessionResult {
    session: WalmartSession | null;
    index: number;
    tried: number;
}

/** Light scan: walk the cached pool from THIS device, one cheap search at a
 * time, and STOP at the first one that works — unlike
 * testWalmartCookiePoolDirect, which deliberately checks all of them. This
 * is the fast path meant for actual use: usually finds a live cookie in a
 * handful of tries (empirically ~40% of the pool works from a real device),
 * without paying for a full pool sweep or a live CloakBrowser mint. */
export const findWorkingWalmartSessionDirect = async (
    onProgress?: (tried: number, total: number) => void,
): Promise<WorkingSessionResult> => {
    const pool = await fetchWalmartSessionPool();
    for (let i = 0; i < pool.length; i++) {
        onProgress?.(i + 1, pool.length);
        try {
            const items = await searchWalmartDirect('milk', pool[i]);
            if (items.length > 0) {
                return { session: pool[i], index: i, tried: i + 1 };
            }
        } catch {
            // dead — keep scanning
        }
    }
    return { session: null, index: -1, tried: pool.length };
};

/** The real end-to-end device path: find a working cookie via the light
 * scan above, then price the whole ingredient list with it. Falls back to
 * fetchWalmartSession() (server-side, may live-mint) only if the device-side
 * scan comes up completely empty — better a slow price than none. */
export const priceWalmartAutoDevice = async (
    ingredientNames: string[],
    onProgress?: (phase: 'scanning' | 'pricing', done: number, total: number) => void,
): Promise<{ prices: Record<string, WalmartDirectItem>; sessionSource: string }> => {
    const scan = await findWorkingWalmartSessionDirect((tried, total) => onProgress?.('scanning', tried, total));
    let session = scan.session;
    let sessionSource = `pool cookie #${scan.index} (${scan.tried} tried)`;
    if (!session) {
        session = await fetchWalmartSession(); // server-side fallback, may live-mint (~30-60s)
        sessionSource = 'server fallback (fresh mint)';
    }
    const prices = await priceIngredientsWalmartDirect(ingredientNames, session, (done, total) =>
        onProgress?.('pricing', done, total),
    );
    return { prices, sessionSource };
};
