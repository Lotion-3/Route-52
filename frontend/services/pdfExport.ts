import * as Print from "expo-print";
import * as Sharing from "expo-sharing";

export type TripItem = {
  name: string;
  qty: number;
  category?: string;
};

export type StorePlan = {
  storeName: string;
  storeAddress: string;
  mapsUrl: string;
  items: TripItem[];
};

export type CombinedTripPlan = {
  logoDataUri?: string; // data:image/png;base64,...
  stores: StorePlan[];
  brandName?: string;   // e.g. "BasketBuddy"
};

function esc(s: string) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderStoreContent(store: StorePlan) {
  // Group items by category
  const categories: Record<string, TripItem[]> = {};
  for (const it of store.items) {
    const cat = it.category || "Other";
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push(it);
  }

  const order = ["Produce", "Meat", "Dairy", "Pantry", "Frozen", "Other"];
  const sortedCats = Object.keys(categories).sort(
    (a, b) => order.indexOf(a) - order.indexOf(b)
  );

  const qrUri = `https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=${encodeURIComponent(store.mapsUrl)}`;

  return `
    <div class="store-section">
        <div class="store-header">
            <div class="store-info">
                <div class="store-name">${esc(store.storeName)}</div>
                <div class="store-addr">${esc(store.storeAddress)}</div>
            </div>
            <div class="store-qr-wrap">
                <img src="${qrUri}" class="qr-small" />
                <div class="qr-hint">Scan for Maps</div>
            </div>
        </div>

        <div class="categories">
            ${sortedCats.map(cat => `
                <div class="category-block">
                    <div class="category-title">${esc(cat)}</div>
                    <div class="item-list">
                        ${categories[cat].map(it => `
                            <div class="item-row">
                                <div class="checkbox"></div>
                                <div class="item-name">${esc(it.name)}</div>
                                <div class="item-qty">${it.qty > 1 ? `x${it.qty}` : ''}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `).join('')}
        </div>
    </div>
    `;
}

export async function exportLinedShoppingListPdf(plan: CombinedTripPlan) {
  const brandName = plan.brandName?.trim() || "BasketBuddy";
  const stores = (plan.stores ?? []).filter((s) => s && Array.isArray(s.items));

  if (!stores.length) throw new Error("No store plans to export.");

  const html = `
  <html>
    <head>
      <meta charset="utf-8" />
      <style>
        @page { margin: 40px; }
        body { 
            margin: 0; 
            padding: 0; 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #fff;
            color: #111827;
        }

        .main-header {
            text-align: center;
            margin-bottom: 40px;
            border-bottom: 2px solid #F3F4F6;
            padding-bottom: 20px;
        }

        .main-title {
            font-size: 28px;
            font-weight: 800;
            color: #111827;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .brand-name {
            color: #4F46E5;
            font-style: italic;
        }

        .store-section {
            margin-bottom: 50px;
            page-break-inside: avoid;
        }

        .store-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            background-color: #F9FAFB;
            padding: 16px;
            border-radius: 12px;
            margin-bottom: 20px;
        }

        .store-name {
            font-size: 20px;
            font-weight: 700;
            color: #111827;
        }

        .store-addr {
            font-size: 13px;
            color: #6B7280;
            margin-top: 4px;
        }

        .store-qr-wrap {
            text-align: center;
        }

        .qr-small {
            width: 60px;
            height: 60px;
            border: 1px solid #E5E7EB;
            border-radius: 6px;
        }

        .qr-hint {
            font-size: 9px;
            color: #9CA3AF;
            margin-top: 4px;
            text-transform: uppercase;
        }

        .category-block {
            margin-bottom: 24px;
        }

        .category-title {
            font-size: 14px;
            font-weight: 800;
            color: #4B5563;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #E5E7EB;
            padding-bottom: 6px;
            margin-bottom: 12px;
        }

        .item-row {
            display: flex;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid #F3F4F6;
        }

        .checkbox {
            width: 18px;
            height: 18px;
            border: 2px solid #D1D5DB;
            border-radius: 4px;
            margin-right: 12px;
        }

        .item-name {
            flex: 1;
            font-size: 15px;
            color: #374151;
        }

        .item-qty {
            font-weight: 700;
            color: #111827;
            font-size: 14px;
            background-color: #F3F4F6;
            padding: 2px 8px;
            border-radius: 4px;
        }

        .footer {
            margin-top: 40px;
            text-align: center;
            font-size: 12px;
            color: #9CA3AF;
        }
      </style>
    </head>
    <body>
      <div class="main-header">
        <div class="main-title">Shopping List</div>
        <div class="brand-name">${esc(brandName)}</div>
      </div>

      ${stores.map(renderStoreContent).join("")}

      <div class="footer">
        Generated by ${esc(brandName)} &bull; Plan your meals, save your money.
      </div>
    </body>
  </html>
  `;

  try {
    const { uri } = await Print.printToFileAsync({
      html,
      base64: false,
    });

    if (await Sharing.isAvailableAsync()) {
      await Sharing.shareAsync(uri, {
        mimeType: "application/pdf",
        dialogTitle: "Share your Shopping List",
        UTI: "com.adobe.pdf",
      });
    } else {
      console.warn("Sharing is not available on this platform");
    }

    return uri;
  } catch (error) {
    console.error("PDF generation or sharing failed", error);
    throw error;
  }
}
