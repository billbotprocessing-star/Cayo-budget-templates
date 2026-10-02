import { useEffect, useRef, useState } from 'react';

export default function Question({ question: q, value, onChange, onNext, onBack, step, total }) {
  const [error, setError] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const progress = Math.round((step / total) * 100);

  const tryNext = () => {
    if (q.type === 'currency') {
      if (value === undefined || value === '') {
        if (q.required) return setError('Please enter an amount.');
        onChange('0');
      } else if (q.required && Number(value) <= 0) {
        return setError('Please enter an amount greater than $0.');
      }
    } else if (!value) {
      return setError('Please choose an option.');
    }
    setError('');
    onNext();
  };

  const pick = (v) => {
    onChange(v);
    setError('');
    setTimeout(onNext, 180);
  };

  const formatted = value ? Number(value).toLocaleString('en-US') : '';

  return (
    <section className="card question">
      <div className="progress" aria-label={`Question ${step + 1} of ${total}`}>
        <div className="progress-bar" style={{ width: `${progress}%` }} />
      </div>
      <p className="eyebrow">
        Question {step + 1} of {total}
      </p>
      <h2>{q.label}</h2>
      {q.help && <p className="help">{q.help}</p>}

      {q.type === 'currency' && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            tryNext();
          }}
        >
          <div className="money-input">
            <span>$</span>
            <input
              ref={inputRef}
              inputMode="numeric"
              placeholder="0"
              value={formatted}
              onChange={(e) => {
                const digits = e.target.value.replace(/[^\d]/g, '').slice(0, 9);
                onChange(digits);
                setError('');
              }}
            />
            <span className="per">/ month</span>
          </div>
        </form>
      )}

      {q.type === 'choice' && (
        <div className="options" role="radiogroup">
          {q.options.map((o) => (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={value === o.value}
              className={`option ${value === o.value ? 'selected' : ''}`}
              onClick={() => pick(o.value)}
            >
              <span className="option-label">{o.label}</span>
              {o.hint && <span className="option-hint">{o.hint}</span>}
            </button>
          ))}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <div className="nav">
        <button className="btn btn-ghost" onClick={onBack}>
          ← Back
        </button>
        <button className="btn btn-primary" onClick={tryNext}>
          {step === total - 1 ? 'See my plan' : 'Next'} →
        </button>
      </div>
    </section>
  );
}
