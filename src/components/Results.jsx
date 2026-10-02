import { BRAND } from '../config';
import { fmt } from '../budget';
import Donut from './Donut';

const ICONS = { alert: '!', warn: '!', info: 'i', tip: '★' };

export default function Results({ budget, lead, onRestart }) {
  const first = lead.name.split(' ')[0];
  const { income, groups, insights, adjustments, targets } = budget;
  const date = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

  return (
    <section className="results">
      <div className="card results-head">
        <div>
          <p className="eyebrow">
            {BRAND.name} · {date}
          </p>
          <h1>{first}, here’s your monthly budget plan</h1>
          <p className="lede">
            Built on <strong>${fmt(income)}/month</strong> take-home pay
            {budget.goalLabel && (
              <>
                {' '}with a focus on <strong>{budget.goalLabel.toLowerCase()}</strong>
              </>
            )}
            .
          </p>
        </div>
        <div className="head-actions no-print">
          <button className="btn btn-primary" onClick={() => window.print()}>
            Download PDF
          </button>
          <button className="btn btn-ghost" onClick={onRestart}>
            Start over
          </button>
        </div>
      </div>

      <div className="card overview">
        <Donut
          segments={groups.map((g) => ({ label: g.label, value: g.total, color: g.color }))}
          centerLabel="Monthly"
          centerValue={`$${fmt(income)}`}
        />
        <div className="split">
          {groups.map((g) => (
            <div className="split-row" key={g.key}>
              <span className="swatch" style={{ background: g.color }} />
              <div className="split-text">
                <strong>{g.label}</strong>
                <span className="muted">Target {g.target}%</span>
              </div>
              <div className="split-num">
                <strong>${fmt(g.total)}</strong>
                <span className="muted">{g.pct}%</span>
              </div>
            </div>
          ))}
          {adjustments.length > 0 && (
            <div className="adjust">
              <p className="adjust-title">
                Why {targets.needs}/{targets.wants}/{targets.savings} instead of 50/30/20?
              </p>
              <ul>
                {adjustments.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="groups">
        {groups.map((g) => (
          <div className="card group" key={g.key}>
            <div className="group-head" style={{ borderColor: g.color }}>
              <h3>{g.label}</h3>
              <span>${fmt(g.total)}</span>
            </div>
            {g.items.length === 0 ? (
              <p className="muted">Nothing left to assign here yet.</p>
            ) : (
              <ul className="items">
                {g.items.map((i) => {
                  const pct = g.total ? (i.amount / g.total) * 100 : 0;
                  return (
                    <li key={i.label}>
                      <div className="item-row">
                        <span>
                          {i.label}
                          {i.note && <small className="muted"> · {i.note}</small>}
                        </span>
                        <strong>${fmt(i.amount)}</strong>
                      </div>
                      <div className="bar">
                        <div style={{ width: `${pct}%`, background: g.color }} />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ))}
      </div>

      {insights.length > 0 && (
        <div className="card">
          <h2 className="section-title">Your personalized insights</h2>
          <ul className="insights">
            {insights.map((ins) => (
              <li key={ins.title} className={`insight ${ins.level}`}>
                <span className="insight-icon" aria-hidden="true">
                  {ICONS[ins.level]}
                </span>
                <div>
                  <strong>{ins.title}</strong>
                  <p>{ins.body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card cta">
        <h2>Want help sticking to it?</h2>
        <p>
          {BRAND.name} can set up simple systems to track your spending, keep business and personal money
          separate, and make tax time painless. Let’s talk through your plan — no pressure.
        </p>
        <a className="btn btn-light btn-lg no-print" href={BRAND.bookingUrl} target="_blank" rel="noreferrer">
          {BRAND.ctaLabel} →
        </a>
        <p className="print-only">Book a call: {BRAND.bookingUrl}</p>
      </div>

      <p className="disclaimer">
        Estimates for utilities, groceries and insurance are based on typical costs for your household size and
        area. Adjust them to your real numbers. This plan is general guidance, not financial advice.
      </p>
    </section>
  );
}
