import { FORM_NAME } from '../config';

const encode = (data) => new URLSearchParams(data).toString();

// Sends the lead to Netlify Forms. In local dev (no Netlify), it just logs.
export async function submitLead(fields) {
  const body = encode({ 'form-name': FORM_NAME, ...fields });

  if (import.meta.env.DEV) {
    console.info('[dev] Lead would be submitted to Netlify Forms:', fields);
    return;
  }

  const res = await fetch('/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) throw new Error(`Form submission failed (${res.status})`);
}
