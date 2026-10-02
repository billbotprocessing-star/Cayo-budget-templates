import { useMemo, useState } from 'react';
import { QUESTIONS } from './questions';
import { buildBudget } from './budget';
import { BRAND } from './config';
import Intro from './components/Intro';
import Question from './components/Question';
import LeadGate from './components/LeadGate';
import Results from './components/Results';

export default function App() {
  const [phase, setPhase] = useState('intro'); // intro | quiz | lead | results
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState({});
  const [lead, setLead] = useState(null);

  const visible = QUESTIONS.filter((q) => !q.showIf || q.showIf(answers));
  const current = visible[step];
  const budget = useMemo(() => buildBudget(answers), [answers]);

  const setAnswer = (id, value) => setAnswers((a) => ({ ...a, [id]: value }));

  const next = () => {
    if (step < visible.length - 1) setStep(step + 1);
    else setPhase('lead');
    window.scrollTo({ top: 0 });
  };
  const back = () => {
    if (step === 0) setPhase('intro');
    else setStep(step - 1);
  };

  const restart = () => {
    setAnswers({});
    setStep(0);
    setPhase('quiz');
  };

  return (
    <div className="app">
      <header className="topbar no-print">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">◐</span>
          {BRAND.name}
        </div>
        <span className="topbar-tag">Free Budget Planner</span>
      </header>

      <main className="main">
        {phase === 'intro' && <Intro onStart={() => setPhase('quiz')} />}

        {phase === 'quiz' && current && (
          <Question
            key={current.id}
            question={current}
            value={answers[current.id]}
            onChange={(v) => setAnswer(current.id, v)}
            onNext={next}
            onBack={back}
            step={step}
            total={visible.length}
          />
        )}

        {phase === 'lead' && (
          <LeadGate
            answers={answers}
            budget={budget}
            onBack={() => setPhase('quiz')}
            onDone={(l) => {
              setLead(l);
              setPhase('results');
              window.scrollTo({ top: 0 });
            }}
          />
        )}

        {phase === 'results' && lead && <Results budget={budget} lead={lead} onRestart={restart} />}
      </main>

      <footer className="footer no-print">
        © {new Date().getFullYear()} {BRAND.name}. This planner gives general estimates, not financial advice.
      </footer>
    </div>
  );
}
