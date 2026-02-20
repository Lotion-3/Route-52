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
  logoDataUri?: string;
  stores: StorePlan[];
  brandName?: string;
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
  const qrUri = `https://api.qrserver.com/v1/create-qr-code/?size=100x100&data=${encodeURIComponent(store.mapsUrl)}`;

  return `
    <div class="store-section">
        <div class="store-header">
            <div class="store-info">
                <div class="store-name">${esc(store.storeName)}</div>
                <div class="store-addr">${esc(store.storeAddress)}</div>
            </div>
            <div class="store-qr-wrap">
                <img src="${qrUri}" class="qr-tiny" />
                <div class="qr-hint">Maps</div>
            </div>
        </div>

        <ul class="item-list">
            ${store.items.map(it => `
                <li class="item-row">
                    <span class="bullet">&bull;</span>
                    <span class="item-name">${esc(it.name)}</span>
                    ${it.qty > 1 ? `<span class="item-qty">x${it.qty}</span>` : ""}
                </li>
            `).join('')}
        </ul>
    </div>
    `;
}

export async function exportLinedShoppingListPdf(plan: CombinedTripPlan) {
  const brandName = plan.brandName?.trim() || "BasketBuddy";
  const stores = (plan.stores ?? []).filter((s) => s && Array.isArray(s.items));

  if (!stores.length) throw new Error("No store plans to export.");

  // PDF generation using standardized Print-CSS for universal compatibility (Mobile & Desktop)
  const html = `
  <!DOCTYPE html>
  <html>
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <style>
        /* CSS Print Standards */
        @page {
            size: A4;
            margin: 15mm;
        }

        body { 
            margin: 0; 
            padding: 0; 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #fff;
            color: #111827;
            font-size: 11pt; /* Use pt for consistent font sizing across OSs */
            line-height: 1.4;
        }

        .main-header {
            display: block;
            border-bottom: 0.5pt solid #E5E7EB;
            padding-bottom: 8pt;
            margin-bottom: 20pt;
            overflow: hidden; /* Clearfix */
        }

        .main-title {
            float: left;
            font-size: 16pt;
            font-weight: 800;
            color: #111827;
        }

        .brand-name {
            float: right;
            color: #6B7280;
            font-size: 9pt;
            text-transform: uppercase;
            letter-spacing: 0.5pt;
            margin-top: 5pt;
        }

        .store-section {
            margin-bottom: 25pt;
            page-break-inside: avoid; /* Standard print rule */
        }

        .store-header {
            display: block;
            margin-bottom: 10pt;
            background-color: #FDFBFA;
            padding: 8pt 10pt;
            border-radius: 4pt;
            border-left: 2.5pt solid #E5E7EB;
            overflow: hidden;
        }

        .store-info {
            float: left;
            width: 75%;
        }

        .store-name {
            font-size: 13pt;
            font-weight: 700;
            color: #111827;
        }

        .store-addr {
            font-size: 9pt;
            color: #6B7280;
            margin-top: 2pt;
        }

        .store-qr-wrap {
            float: right;
            text-align: right;
            width: 20%;
        }

        .qr-tiny {
            width: 35pt;
            height: 35pt;
            border-radius: 3pt;
        }

        .qr-hint {
            font-size: 7pt;
            color: #9CA3AF;
            margin-top: 1pt;
            text-transform: uppercase;
        }

        .item-list {
            list-style: none;
            padding: 0;
            margin: 0;
            clear: both;
        }

        .item-row {
            display: block;
            padding: 4pt 0;
            border-bottom: 0.5pt solid #F9FAFB;
            overflow: hidden;
        }

        .bullet {
            float: left;
            color: #D1D5DB;
            margin-right: 6pt;
            font-size: 14pt;
            line-height: 1;
        }

        .item-name {
            float: left;
            color: #374151;
            max-width: 80%;
        }

        .item-qty {
            float: right;
            font-weight: 700;
            color: #111827;
            font-size: 9pt;
            background-color: #F3F4F6;
            padding: 1pt 5pt;
            border-radius: 2pt;
        }

        .footer {
            margin-top: 30pt;
            padding-top: 10pt;
            border-top: 0.5pt solid #F3F4F6;
            text-align: center;
            font-size: 8pt;
            color: #9CA3AF;
            clear: both;
        }

        /* Clearfix for Windows/Desktop Browsers */
        .main-header::after, .store-header::after, .item-row::after {
            content: "";
            display: table;
            clear: both;
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
