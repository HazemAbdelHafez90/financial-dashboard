const APP_BASE_URL = 'https://financial-report-eight.vercel.app/';

function json(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store'
    }
  });
}

function normalizeArabicDigits(value = '') {
  return String(value)
    .replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d))
    .replace(/[٫،]/g, '.');
}

function normalizeWhitespace(value = '') {
  return String(value).replace(/\s+/g, ' ').trim();
}

function sanitizeMessage(message = '') {
  return normalizeWhitespace(normalizeArabicDigits(message));
}

/* Currency token: any ISO 3-letter code we support, plus Arabic EGP synonyms.
   Capture group 1 = currency (may be absent → assume EGP).
   Capture group 2 = numeric amount. */
const CURRENCY_TOKEN = '(EGP|USD|EUR|GBP|SAR|AED|CHF|JPY|جم|جنيه)';

function extractAmountAndCurrency(text) {
  const patterns = [
    new RegExp(`تم سحب مبلغ\\s*${CURRENCY_TOKEN}?\\s*([0-9]+(?:\\.[0-9]+)?)`, 'i'),
    new RegExp(`تم تنفيذ تحويل(?:\\s+لحظي)?\\s+بمبلغ\\s*${CURRENCY_TOKEN}?\\s*([0-9]+(?:\\.[0-9]+)?)`, 'i'),
    new RegExp(`تم تحويل مبلغ\\s*${CURRENCY_TOKEN}?\\s*([0-9]+(?:\\.[0-9]+)?)`, 'i'),
    new RegExp(`تم خصم\\s*(?:مبلغ\\s*)?${CURRENCY_TOKEN}?\\s*([0-9]+(?:\\.[0-9]+)?)`, 'i'),
    new RegExp(`تم خصم مبلغ\\s*${CURRENCY_TOKEN}?\\s*([0-9]+(?:\\.[0-9]+)?)`, 'i'),
    new RegExp(`بمبلغ\\s*${CURRENCY_TOKEN}?\\s*([0-9]+(?:\\.[0-9]+)?)`, 'i')
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) {
      const rawCur = (match[1] || '').toUpperCase();
      const currency = (!rawCur || rawCur === 'جم' || rawCur === 'جنيه') ? 'EGP' : rawCur;
      return { amount: Number.parseFloat(match[2]), currency };
    }
  }
  return null;
}

/* Back-compat shim — some callers still expect a bare number */
function extractAmount(text) {
  const r = extractAmountAndCurrency(text);
  return r ? r.amount : null;
}

function extractDate(text) {
  // YYYY/MM/DD or YYYY-MM-DD (e.g. "في تاريخ 2026/06/23")
  const iso = text.match(/(?:في|بتاريخ)(?:\s+تاريخ)?\s*([0-9]{4})[\/-]([0-9]{2})[\/-]([0-9]{2})/);
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;
  // DD/MM/YYYY or DD-MM-YY (e.g. "بتاريخ 18-07-2026", "في 02/07/26")
  const match = text.match(/(?:في|بتاريخ)\s*([0-9]{2})[\/-]([0-9]{2})[\/-]([0-9]{2,4})/);
  if (!match) return new Date().toISOString().slice(0, 10);
  const day = match[1];
  const month = match[2];
  const year = match[3].length === 2 ? `20${match[3]}` : match[3];
  return `${year}-${month}-${day}`;
}

// Money direction: 'in' = arrived in the account, 'out' = left it.
function detectDirection(text) {
  if (/إلى حسابك|لحسابك(?:م)?|تم إضافة|تم إيداع/.test(text)) return 'in';
  if (/من حسابك|تم خصم|تم سحب/.test(text)) return 'out';
  return 'out';
}

// Counterparty on a transfer, e.g. "... من احمد محمد ابراهيم موسي برقم مرجعي ..."
// Restricted to an Arabic name so it never captures "حسابك" or reference numbers.
function extractCounterparty(text) {
  const m = text.match(/من\s+((?!حسابك)[؀-ۿ][؀-ۿ\s]+?)\s+(?:برقم مرجعي|بتاريخ|في\s)/);
  return m?.[1] ? normalizeWhitespace(m[1]) : '';
}

function extractMerchant(text) {
  if (/تم تنفيذ تحويل(?:\s+لحظي)?/.test(text)) {
    return 'Instant Transfer';
  }

  const patterns = [
    /من\s+([A-Z][A-Z0-9&.'\- ]+?)\s+في\s+[0-9]{2}[\/-][0-9]{2}[\/-][0-9]{2,4}/,
    /([A-Z][A-Z0-9&.'\- ]{2,})\s+في\s+[0-9]{2}[\/-][0-9]{2}[\/-][0-9]{2,4}/,
    /عند\s+(.+?)\s+في\s+[0-9]{2}[\/-][0-9]{2}[\/-][0-9]{2,4}/,
    /عند\s+(.+?)\s+[0-9]{2}[\/-][0-9]{2}[\/-][0-9]{2,4}/,
    /عند\s+(.+?)\s+في\b/,
    /في\s+(.+?)\s+برقم مرجعي/i
  ];

  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) {
      let merchant = normalizeWhitespace(match[1]);
      merchant = merchant.replace(/\b\d{4}\*+\b/g, '').trim();
      merchant = merchant.replace(/\s{2,}/g, ' ');
      if (merchant) return merchant;
    }
  }
  return '';
}

function inferCategory(merchant) {
  const name = merchant.toUpperCase();
  if (name.includes('CHILLOUT') || name.includes('TOTAL') || name.includes('SHELL') || name.includes('MOBIL')) return 'Fuel';
  if (name.includes('UBER') || name.includes('CAREEM')) return 'Hazem Personal';
  if (name.includes('MARKET') || name.includes('CARREFOUR') || name.includes('HYPER') || name.includes('GOURMET')) return 'Home';
  return 'Hazem Personal';
}

// Is this a bank message we recognise at all?
function isRecognized(text) {
  return /تم سحب|تم خصم|تحويل|تم إضافة|تم إيداع/.test(text);
}

// Classify a recognised message into its direction, budget type, category and a
// human-readable description. Incoming money is flagged type 'Received' so the app
// logs it in its own list and never counts it as spend.
function classifyTransaction(text) {
  const direction = detectDirection(text);
  const isTransfer = /تحويل/.test(text);

  if (direction === 'in') {
    const cp = extractCounterparty(text);
    return {
      direction, isIncoming: true, type: 'Received', category: 'Received',
      description: cp || (isTransfer ? 'Instant Transfer (received)' : 'Deposit')
    };
  }
  if (isTransfer) {
    const cp = extractCounterparty(text);
    return {
      direction, isIncoming: false, type: 'Planned', category: 'Transfers',
      description: cp || 'Instant Transfer'
    };
  }
  // Card / debit purchase
  const merchant = extractMerchant(text);
  return {
    direction, isIncoming: false, type: 'Planned',
    category: merchant ? inferCategory(merchant) : 'Hazem Personal',
    description: merchant || 'Card Purchase'
  };
}

function buildOpenUrl(parsed) {
  const url = new URL(APP_BASE_URL);
  url.searchParams.set('shortcut', 'expense');
  url.searchParams.set('amount', String(parsed.amount));
  url.searchParams.set('merchant', parsed.merchant);
  url.searchParams.set('date', parsed.date);
  if (parsed.currency && parsed.currency !== 'EGP') url.searchParams.set('currency', parsed.currency);
  if (parsed.category) url.searchParams.set('category', parsed.category);
  url.searchParams.set('type', parsed.type || 'Planned');
  url.searchParams.set('autosave', parsed.category ? '1' : '0');
  url.searchParams.set('source', 'bank-sms');
  return url.toString();
}

async function readMessage(request) {
  if (request.method === 'GET') {
    if (!request.url) return '';
    const params = new URL(request.url).searchParams;
    return params.get('sms') || params.get('message') || '';
  }

  const contentType = request.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const body = await request.json().catch(() => ({}));
    return body.sms || body.message || '';
  }

  if (contentType.includes('application/x-www-form-urlencoded')) {
    const body = await request.text();
    const params = new URLSearchParams(body);
    return params.get('sms') || params.get('message') || '';
  }

  return await request.text();
}

export function parseBankMessage(message) {
  const text = sanitizeMessage(message);

  if (!isRecognized(text)) {
    return {
      ok: false,
      kind: 'unknown',
      shouldCreateExpense: false,
      reason: 'Could not recognize this bank message format.'
    };
  }

  const amountInfo = extractAmountAndCurrency(text);
  const amount = amountInfo?.amount;
  const currency = amountInfo?.currency || 'EGP';
  const date = extractDate(text);
  const tx = classifyTransaction(text);

  if (!amount) {
    return {
      ok: false,
      kind: tx.isIncoming ? 'received' : 'expense',
      shouldCreateExpense: false,
      reason: 'Could not extract the amount from the message.',
      normalizedMessage: text
    };
  }

  const parsed = {
    amount,               // raw (may be foreign); caller converts to EGP
    currency,             // e.g. "USD", "EGP"
    merchant: tx.description,  // merchant (purchase) or counterparty (transfer)
    date,
    category: tx.category,
    type: tx.type,        // 'Planned' for spend, 'Received' for incoming money
    direction: tx.direction,
    isIncoming: tx.isIncoming
  };

  return {
    ok: true,
    kind: tx.isIncoming ? 'received' : 'expense',
    shouldCreateExpense: true,
    parsed,
    openUrl: buildOpenUrl(parsed),
    normalizedMessage: text
  };
}

export const runtime = 'edge';

export async function GET(request) {
  const message = await readMessage(request);
  if (!message) {
    return json({
      ok: false,
      error: 'Pass a bank message in the `sms` query parameter.'
    }, 400);
  }
  return json(parseBankMessage(message));
}

export async function POST(request) {
  const message = await readMessage(request);
  if (!message) {
    return json({
      ok: false,
      error: 'Pass a bank message in the request body as `sms`.'
    }, 400);
  }
  return json(parseBankMessage(message));
}
