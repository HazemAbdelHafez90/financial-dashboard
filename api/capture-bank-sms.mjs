import { parseBankMessage } from './parse-bank-message.mjs';

const SUPABASE_URL = 'https://ppxzhhcceivcdxxxwxqh.supabase.co';
const EXPENSES_ENDPOINT = `${SUPABASE_URL}/rest/v1/expenses`;

function json(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store'
    }
  });
}

function dateToMonthKey(dateStr) {
  if (!dateStr) return null;
  const [y, m, d] = dateStr.split('-').map(Number);
  if (d >= 19) {
    const next = new Date(y, m, 1);
    return next.toISOString().slice(0, 7);
  }
  return dateStr.slice(0, 7);
}

async function readSms(request) {
  const contentType = request.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    const body = await request.json().catch(() => ({}));
    return {
      sms: body.sms || '',
      category: body.category || '',
      type: body.type || ''
    };
  }

  if (contentType.includes('application/x-www-form-urlencoded')) {
    const body = await request.text();
    const params = new URLSearchParams(body);
    return {
      sms: params.get('sms') || '',
      category: params.get('category') || '',
      type: params.get('type') || ''
    };
  }

  const raw = await request.text();
  return { sms: raw, category: '', type: '' };
}

function isAuthorized(request) {
  const secret = process.env.BANK_SMS_SHARED_SECRET;
  if (!secret) return { ok: false, reason: 'Missing BANK_SMS_SHARED_SECRET env var.' };

  const provided =
    request.headers.get('x-automation-key') ||
    request.headers.get('authorization')?.replace(/^Bearer\s+/i, '') ||
    '';

  if (!provided || provided !== secret) {
    return { ok: false, reason: 'Unauthorized automation request.' };
  }

  return { ok: true };
}

async function insertExpense(expense) {
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!serviceRoleKey) {
    throw new Error('Missing SUPABASE_SERVICE_ROLE_KEY env var.');
  }

  const response = await fetch(EXPENSES_ENDPOINT, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      apikey: serviceRoleKey,
      authorization: `Bearer ${serviceRoleKey}`,
      prefer: 'return=representation'
    },
    body: JSON.stringify(expense)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Supabase insert failed: ${response.status} ${text}`);
  }

  const rows = await response.json().catch(() => []);
  return rows[0] || expense;
}

export const runtime = 'edge';

export async function POST(request) {
  console.log('[capture-bank-sms] request received', {
    method: request.method,
    hasAuthHeader: !!request.headers.get('x-automation-key'),
    contentType: request.headers.get('content-type') || ''
  });

  const auth = isAuthorized(request);
  if (!auth.ok) {
    console.warn('[capture-bank-sms] authorization failed', { reason: auth.reason });
    return json({ ok: false, error: auth.reason }, 401);
  }

  const payload = await readSms(request);
  console.log('[capture-bank-sms] payload parsed', {
    hasSms: !!payload.sms,
    smsLength: payload.sms?.length || 0,
    categoryOverride: payload.category || null,
    typeOverride: payload.type || null
  });

  if (!payload.sms) {
    console.warn('[capture-bank-sms] missing sms field');
    return json({ ok: false, error: 'Pass the whole bank message in the `sms` field.' }, 400);
  }

  const parsedResult = parseBankMessage(payload.sms);
  console.log('[capture-bank-sms] parse result', {
    ok: parsedResult.ok,
    kind: parsedResult.kind || 'unknown',
    shouldCreateExpense: !!parsedResult.shouldCreateExpense,
    reason: parsedResult.reason || null,
    parsed: parsedResult.parsed || null
  });

  if (!parsedResult.ok || !parsedResult.shouldCreateExpense) {
    return json({
      ok: parsedResult.ok,
      kind: parsedResult.kind || 'unknown',
      inserted: false,
      reason: parsedResult.reason || 'Message was not recognized as an expense.'
    }, parsedResult.kind === 'transfer' ? 200 : 422);
  }

  const parsed = parsedResult.parsed;
  const category = payload.category || parsed.category;
  const type = payload.type || parsed.type || 'Planned';
  const date = parsed.date;

  if (!category) {
    return json({
      ok: true,
      inserted: false,
      manualReview: true,
      kind: parsedResult.kind,
      reason: 'Category is empty, so this message was parsed but not inserted.',
      parsed,
      openUrl: parsedResult.openUrl
    });
  }

  const expense = {
    id: crypto.randomUUID(),
    date,
    amount: parsed.amount,
    category,
    description: parsed.merchant,
    type,
    month_key: dateToMonthKey(date)
  };

  try {
    console.log('[capture-bank-sms] inserting expense', expense);
    const inserted = await insertExpense(expense);
    console.log('[capture-bank-sms] insert succeeded', { id: inserted.id, category: inserted.category, amount: inserted.amount });
    return json({
      ok: true,
      inserted: true,
      kind: parsedResult.kind,
      expense: inserted
    });
  } catch (error) {
    console.error('[capture-bank-sms] insert failed', { message: error.message, expense });
    return json({
      ok: false,
      inserted: false,
      error: error.message,
      parsed
    }, 500);
  }
}
