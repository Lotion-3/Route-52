"""
Probe 10 — extract product cards directly from the rendered DOM.
If Costco SSR-embeds prices in the HTML, this is simpler than API chasing.
"""
import json, re, time
from urllib.parse import quote

from cloakbrowser import launch
browser = launch(headless=True)
ctx = browser.new_context()

TERMS = ["olive oil", "eggs", "white rice", "chicken breast"]

def extract_products(page) -> list[dict]:
    """Try every selector pattern to find product name + price in the DOM."""
    # 1. Look for structured product JSON in <script type="application/ld+json">
    ld = page.evaluate("""() => {
        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
        return Array.from(scripts).map(s => s.textContent);
    }""")
    for raw in ld:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("@type") in ("Product","ItemList"):
                return [{"source":"ld+json","data":str(data)[:300]}]
        except Exception:
            pass

    # 2. Try React fiber state to get product data
    react_products = page.evaluate("""() => {
        try {
            // Look for Next.js page props
            if (window.__NEXT_DATA__) return {type:'nextdata', data: JSON.stringify(window.__NEXT_DATA__).substring(0, 2000)};
            // Look for React root
            const root = document.getElementById('__NEXT_DATA__');
            if (root) return {type:'next_el', data: root.textContent.substring(0,2000)};
        } catch(e) { return {type:'err', data: String(e)}; }
        return null;
    }""")
    if react_products:
        return [{"source":"react","data":str(react_products)[:500]}]

    # 3. Extract visible text from product cards
    cards = page.evaluate("""() => {
        const results = [];
        // Try common product card selectors
        const selectors = [
            '[automation-id*="product"]',
            '[class*="product-list"]',
            '[class*="ProductTile"]',
            '[class*="product-tile"]',
            'article[class*="product"]',
            '[data-testid*="product"]',
            '.product',
            'li[class*="product"]',
        ];
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            if (els.length > 0) {
                for (const el of Array.from(els).slice(0, 8)) {
                    const text = el.innerText || el.textContent || '';
                    const cleaned = text.replace(/\\s+/g, ' ').trim().substring(0, 200);
                    if (cleaned.length > 10) results.push({sel, text: cleaned});
                }
                if (results.length > 0) break;
            }
        }
        return results;
    }""")
    if cards:
        return [{"source":"dom_cards","data":cards[:5]}]

    # 4. Look for price patterns in page text
    prices = page.evaluate("""() => {
        const body = document.body.innerText || '';
        const matches = body.match(/\\$\\d+\\.\\d{2}/g);
        return matches ? matches.slice(0, 20) : [];
    }""")

    # 5. Check for any product name patterns
    names = page.evaluate("""() => {
        const els = document.querySelectorAll('h2, h3, [class*="description"], [class*="title"]');
        return Array.from(els).slice(0, 10).map(e => (e.innerText || e.textContent || '').trim().substring(0,80)).filter(t => t.length > 5);
    }""")

    return [{"source":"raw", "prices": prices[:10], "names": names[:8]}]


page = ctx.new_page()
print("[probe10] Warming session ...")
try:
    page.goto("https://www.costco.com/", wait_until="networkidle", timeout=60000)
except Exception:
    pass
time.sleep(3)

for term in TERMS:
    print(f"\n[probe10] Searching: '{term}' ...")
    try:
        page.goto(f"https://www.costco.com/CatalogSearch?keyword={quote(term)}&pageSize=24",
                  wait_until="networkidle", timeout=60000)
    except Exception:
        pass
    time.sleep(6)  # extra wait for React hydration

    print(f"  URL: {page.url}")
    print(f"  Title: {page.title()!r}")

    products = extract_products(page)
    for p in products[:3]:
        print(f"  {p}")

    # Also dump a small HTML snippet with likely product/price areas
    html_excerpt = page.evaluate("""() => {
        // Find sections likely to contain product data
        const sections = document.querySelectorAll('main, [role="main"], #main-content');
        const target = sections[0] || document.body;
        return target.innerHTML.substring(0, 3000);
    }""")
    snippet_prices = re.findall(r'\$\d+\.\d{2}', html_excerpt)
    print(f"  Price patterns in HTML: {snippet_prices[:10]}")

    # Save HTML for this term
    fname = f".cache/costco_{term.replace(' ','_')}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(page.content())
    print(f"  Saved HTML to {fname} ({len(page.content())} chars)")

page.close()
ctx.close()
browser.close()
print("\n[probe10] Done.")
