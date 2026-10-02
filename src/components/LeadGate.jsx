import { useState } from 'react';
import { BRAND } from '../config';
import { submitLead } from '../lib/submitLead';
import { QUESTIONS } from '../questions';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Human-readable summary of every answer, sent along with the lead.
function summarizeAnswers(answers) {
  return QUESTIONS.filter((q) => answers[q.id] !== undefined)
    .map((q) => {
      const v = answers[q.id];
      const shown =
        q.type === 'currency'
          ? `$${Number(v).toLocaleString('en-US')}`
          : q.options.find((o) => o.value === v)?.label ?? v;
      return `${q.label} ${shown}`;
    })
    .join('\n');
}

export default function LeadGate({ answers, budget, onBack, onDone }) {
  const [form, setForm] = useState({ name: '', email: '', phone: '', consent: false, botField: '' });
  const [errors, setErrors] = useState({});
  const [status, setStatus] = useState('idle'); // idle | sending | error

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    const errs = {};
    if (!form.name.trim()) errs.name = 'Please enter your name.';
    if (!EMAIL_RE.test(form.email.trim())) errs.email = 'Please enter a valid email.';
    if (!form.consent) errs.consent = 'Please agree so we can send your plan.';
    setErrors(errs);
    if (Object.keys(errs).length) return;

    setStatus('sending');
    const [needs, wants, savings] = budget.groups.map((g) => g.pct);
    try {
      await submitLead({
        'bot-field': form.botField,
        name: form.name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        consent: 'yes',
        monthly_income: `$${Number(answers.income || 0).toLocaleString('en-US')}`,
        primary_goal: budget.goalLabel,
        business_owner: answers.business ?? '',
        emergency_fund: answers.emergencyFund ?? '',
        debt_balance: `$${Number(answers.debtBalance || 0).toLocaleString('en-US')}`,
        budget_split: `Needs ${needs}% / Wants ${wants}% / Savings ${savings}%`,
        all_answers: summarizeAnswers(answers),
      });
      onDone({ name: form.name.trim(), email: form.email.trim() });
    } catch (err) {
      console.error(err);
      setStatus('error');
    }
  };

  return (
    <section className="card lead">
      <p className="eyebrow">Your plan is ready</p>
      <h2>Where should we send your budget?</h2>
      <p className="help">
        Enter your name and email to unlock your personalized breakdown. You’ll be able to view it right away
        and download it as a PDF.
      </p>

      <form onSubmit={submit} noValidate>
        <p hidden>
          <label>
            Don’t fill this out: <input name="bot-field" value={form.botField} onChange={set('botField')} />
          </label>
        </p>

        <label className="field">
          <span>Full name</span>
          <input autoComplete="name" value={form.name} onChange={set('name')} />
          {errors.name && <em className="error">{errors.name}</em>}
        </label>

        <label className="field">
          <span>Email</span>
          <input type="email" autoComplete="email" value={form.email} onChange={set('email')} />
          {errors.email && <em className="error">{errors.email}</em>}
        </label>

        <label className="field">
          <span>
            Phone <small>(optional)</small>
          </span>
          <input type="tel" autoComplete="tel" value={form.phone} onChange={set('phone')} />
        </label>

        <label className="consent">
          <input type="checkbox" checked={form.consent} onChange={set('consent')} />
          <span>
            I agree to receive my budget plan and occasional money tips from {BRAND.name}. Unsubscribe anytime.
          </span>
        </label>
        {errors.consent && <em className="error">{errors.consent}</em>}

        {status === 'error' && (
          <p className="error">Something went wrong sending your info. Please check your connection and try again.</p>
        )}

        <div className="nav">
          <button type="button" className="btn btn-ghost" onClick={onBack}>
            ← Back
          </button>
          <button type="submit" className="btn btn-primary" disabled={status === 'sending'}>
            {status === 'sending' ? 'Building your plan…' : 'Show my budget →'}
          </button>
        </div>
      </form>
    </section>
  );
}
