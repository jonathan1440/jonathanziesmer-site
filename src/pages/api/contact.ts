import type { APIRoute } from 'astro';
import { RESEND_API_KEY, RESEND_FROM_EMAIL } from 'astro:env/server';
import { Resend } from 'resend';
import { site } from '../../data/site';

export const prerender = false;

const MAX_BODY_BYTES = 20_000;

function seeOther(status: string): Response {
  return new Response(null, {
    status: 303,
    headers: { Location: `/contact?status=${status}` },
  });
}

function field(value: FormDataEntryValue | null, max: number, multiline = false): string {
  if (typeof value !== 'string') return '';
  const normalized = multiline
    ? value.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
    : value.replace(/[\r\n]+/g, ' ');
  return normalized.trim().slice(0, max);
}

function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export const POST: APIRoute = async ({ request }) => {
  const lengthHeader = request.headers.get('content-length');
  if (lengthHeader) {
    const declared = Number(lengthHeader);
    if (!Number.isFinite(declared) || declared > MAX_BODY_BYTES) {
      return seeOther('invalid');
    }
  }

  let body: ArrayBuffer;
  try {
    body = await request.arrayBuffer();
  } catch {
    return seeOther('invalid');
  }
  if (body.byteLength > MAX_BODY_BYTES) {
    return seeOther('invalid');
  }

  let form: FormData;
  try {
    form = await new Request(request.url, {
      method: 'POST',
      headers: request.headers,
      body,
    }).formData();
  } catch {
    return seeOther('invalid');
  }

  if (field(form.get('website'), 200)) {
    return seeOther('sent');
  }

  const name = field(form.get('name'), 100);
  const email = field(form.get('email'), 254);
  const subject = field(form.get('subject'), 150);
  const message = field(form.get('message'), 5000, true);

  if (!name || !email || !message || !isEmail(email)) {
    return seeOther('invalid');
  }

  if (!RESEND_API_KEY || !RESEND_FROM_EMAIL) {
    return seeOther('unconfigured');
  }

  const resend = new Resend(RESEND_API_KEY);
  const { error } = await resend.emails.send({
    from: RESEND_FROM_EMAIL,
    to: [site.email],
    replyTo: email,
    subject: subject || `Portfolio note from ${name}`,
    text: [`Name: ${name}`, `Email: ${email}`, '', message].join('\n'),
  });

  if (error) {
    return seeOther('failed');
  }

  return seeOther('sent');
};
