import { BRAND } from '../config';

export default function Intro({ onStart }) {
  return (
    <section className="card intro">
      <p className="eyebrow">Free · Takes about 3 minutes</p>
      <h1>Get a budget plan built around your real life.</h1>
      <p className="lede">
        Answer 12 quick questions about your income, bills and goals. We’ll build a personalized monthly
        budget with a clear breakdown you can download and keep.
      </p>
      <ul className="checks">
        <li>Personalized needs / wants / savings split</li>
        <li>Debt payoff and emergency fund timelines</li>
        <li>Printable PDF of your plan</li>
      </ul>
      <button className="btn btn-primary btn-lg" onClick={onStart}>
        Start my budget →
      </button>
      <p className="fine">Brought to you by {BRAND.name}. Your answers stay private.</p>
    </section>
  );
}
