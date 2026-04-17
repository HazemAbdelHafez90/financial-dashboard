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

function extractAmount(text) {
  const patterns = [
    /تم سحب مبلغ\s*(?:EGP|جم|جنيه)?\s*([0-9]+(?:\.[0-9]+)?)/i,
    /تم تنفيذ تحويل(?:\s+لحظي)?\s+بمبلغ\s*(?:EGP|جم|جنيه)?\s*([0-9]+(?:\.[0-9]+)?)/i,
    /تم خصم\s*(?:مبلغ\s*)?(?:EGP|جم|جنيه)?\s*([0-9]+(?:\.[0-9]+)?)/i,
    /تم خصم مبلغ\s*(?:EGP|جم|جنيه)?\s*([0-9]+(?:\.[0-9]+)?)/i,
    /بمبلغ\s*(?:EGP|جم|جنيه)?\s*([0-9]+(?:\.[0-9]+)?)/i
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return Number.parseFloat(match[1]);
  }
  return null;
}

function extractDate(text) {
  const match = text.match(/(?:في|بتاريخ)\s*([0-9]{2})[\/-]([0-9]{2})[\/-]([0-9]{2,4})/);
  if (!match) return new Date().toISOString().slice(0, 10);
  const day = match[1];
  const month = match[2];
  const year = match[3].length === 2 ? `20${match[3]}` : match[3];
  return `${year}-${month}-${day}`;
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

function resolveCategory(text, merchant) {
  if (/تم تنفيذ تحويل|تحويل لحظي/.test(text)) return 'Hazem Personal';
  if (/تم سحب مبلغ/.test(text)) return '';
  return inferCategory(merchant);
}

function classifyMessage(text) {
  if (/تم سحب مبلغ/.test(text)) return 'expense';
  if (/تم تنفيذ تحويل|تحويل لحظي/.test(text)) return 'expense';
  if (/تم خصم(?:\s+مبلغ)?/.test(text)) return 'expense';
  return 'unknown';
}

function buildOpenUrl(parsed) {
  const url = new URL(APP_BASE_URL);
  url.searchParams.set('shortcut', 'expense');
  url.searchParams.set('amount', String(parsed.amount));
  url.searchParams.set('merchant', parsed.merchant);
  url.searchParams.set('date', parsed.date);
  if (parsed.category) url.searchParams.set('category', parsed.category);
  url.searchParams.set('type', 'Planned');
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
  const kind = classifyMessage(text);

  if (kind !== 'expense') {
    return {
      ok: false,
      kind,
      shouldCreateExpense: false,
      reason: 'Could not recognize this bank message format.'
    };
  }

  const amount = extractAmount(text);
  const merchant = extractMerchant(text);
  const date = extractDate(text);

  if (!amount || !merchant) {
    return {
      ok: false,
      kind,
      shouldCreateExpense: false,
      reason: 'Could not extract amount or merchant from the message.',
      normalizedMessage: text
    };
  }

  const parsed = {
    amount,
    merchant,
    date,
    category: resolveCategory(text, merchant),
    type: 'Planned'
  };

  return {
    ok: true,
    kind,
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
