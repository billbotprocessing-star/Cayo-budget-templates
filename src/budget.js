// Adaptive budget engine.
// Starts from 50/30/20 (needs / wants / savings) and shifts the targets
// based on the assessment answers, then fills in line items.

const num = (v) => {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : 0;
};
const round = (n, to = 5) => Math.round(n / to) * to;

const COL = { low: 0.9, average: 1, high: 1.2 };
const HH_FACTOR = { '1': 1, '2': 1.35, '3-4': 1.7, '5+': 2.1 };
const GROCERIES = { '1': 400, '2': 700, '3-4': 1050, '5+': 1400 };

export const GROUP_COLORS = {
  needs: '#1f6f78',
  wants: '#e8a33d',
  savings: '#4c9f70',
};

const GOAL_LABELS = {
  debt: 'Pay off debt',
  emergency: 'Build a safety net',
  purchase: 'Save for something big',
  retire: 'Invest for the future',
  organize: 'Get organized',
};

const EF_MONTHS = { none: 0, under1: 0.5, '1to3': 2, '3to6': 4.5, '6plus': 6 };

// Months to pay off a balance at an assumed APR; null if payment never covers interest.
function payoffMonths(balance, payment, apr = 0.2) {
  if (balance <= 0) return 0;
  if (payment <= 0) return null;
  const r = apr / 12;
  if (payment <= balance * r) return null;
  return Math.ceil(-Math.log(1 - (r * balance) / payment) / Math.log(1 + r));
}

const fmtMonths = (m) => {
  if (m == null) return 'more than 10 years';
  if (m <= 1) return 'about 1 month';
  if (m < 24) return `about ${m} months`;
  return `about ${(m / 12).toFixed(1)} years`;
};

export function buildBudget(a) {
  const income = num(a.income);
  const housing = num(a.housing);
  const transport = num(a.transport);
  const debtBalance = num(a.debtBalance);
  const debtMin = debtBalance > 0 ? num(a.debtMinimums) : 0;
  const hh = a.household || '1';
  const col = COL[a.costOfLiving] ?? 1;
  const hasDebt = debtBalance > 0;
  const variable = a.incomeType && a.incomeType !== 'steady';
  const lowEF = ['none', 'under1'].includes(a.emergencyFund);

  // ---------- 1. Adaptive targets ----------
  const t = { needs: 50, wants: 30, savings: 20 };
  const adjustments = [];

  if (a.costOfLiving === 'high') {
    t.needs += 5; t.wants -= 5;
    adjustments.push('Needs raised to reflect your higher cost of living.');
  } else if (a.costOfLiving === 'low') {
    t.needs -= 5; t.savings += 5;
    adjustments.push('Your lower cost of living frees up extra for savings.');
  }
  if (variable) {
    t.wants -= 5; t.savings += 5;
    adjustments.push('Extra savings cushion because your income varies.');
  }
  if (hasDebt && a.goal === 'debt') {
    t.wants -= 5; t.savings += 5;
    adjustments.push('Wants trimmed to speed up your debt payoff.');
  }
  if (lowEF && t.wants > 15) {
    t.wants -= 5; t.savings += 5;
    adjustments.push('Wants trimmed to build your emergency fund faster.');
  }
  if (t.wants < 15) {
    const diff = 15 - t.wants;
    t.wants = 15; t.savings -= diff;
  }

  // ---------- 2. Needs (mostly actual numbers) ----------
  const needsItems = [
    { label: 'Housing', amount: housing, note: 'Your rent / mortgage' },
    { label: 'Utilities & phone', amount: round(160 * HH_FACTOR[hh] * col) },
    { label: 'Groceries', amount: round((GROCERIES[hh] ?? 400) * col) },
    { label: 'Transportation', amount: transport, note: 'Your estimate' },
    { label: 'Insurance & health', amount: round(Math.max(100, income * 0.04)) },
  ];
  if (debtMin > 0) needsItems.push({ label: 'Minimum debt payments', amount: debtMin, note: 'Required minimums' });

  const needsTotal = needsItems.reduce((s, i) => s + i.amount, 0);
  const remaining = income - needsTotal;
  const shortfall = remaining < 0 ? -remaining : 0;

  // ---------- 3. Split what's left between wants and savings ----------
  let wantsTotal = 0;
  let savingsTotal = 0;
  if (remaining > 0) {
    const wantsShare = t.wants / (t.wants + t.savings);
    const wantsCap = (income * t.wants) / 100;
    wantsTotal = Math.min(remaining * wantsShare, wantsCap);
    savingsTotal = remaining - wantsTotal;
  }

  const wantsItems = [
    { label: 'Dining out & takeout', amount: wantsTotal * 0.3 },
    { label: 'Entertainment & hobbies', amount: wantsTotal * 0.2 },
    { label: 'Shopping & personal care', amount: wantsTotal * 0.3 },
    { label: 'Subscriptions', amount: wantsTotal * 0.08 },
    { label: 'Travel & fun money', amount: wantsTotal * 0.12 },
  ];

  // ---------- 4. Savings allocation by priority ----------
  const w = {
    emergency: lowEF ? 2.5 : a.emergencyFund === '1to3' ? 1.5 : a.emergencyFund === '6plus' ? 0.2 : 0.7,
    debt: hasDebt ? 1.5 : 0,
    retire: a.retirement === 'payroll' ? 0.7 : 1.2,
    goal: a.goal === 'purchase' ? 1 : 0.4,
  };
  if (a.goal === 'debt' && hasDebt) w.debt += 2;
  if (a.goal === 'emergency') w.emergency += 2;
  if (a.goal === 'retire') w.retire += 2;
  if (a.goal === 'purchase') w.goal += 2;
  const wSum = Object.values(w).reduce((s, v) => s + v, 0);
  const share = (k) => (savingsTotal * w[k]) / wSum;

  const savingsItems = [
    { label: 'Emergency fund', amount: share('emergency') },
    ...(hasDebt ? [{ label: 'Extra debt payments', amount: share('debt'), note: 'On top of minimums' }] : []),
    { label: 'Retirement & investing', amount: share('retire') },
    { label: a.goal === 'purchase' ? 'Big purchase fund' : 'Goals & sinking funds', amount: share('goal') },
  ];

  const clean = (items) =>
    items.map((i) => ({ ...i, amount: round(i.amount) })).filter((i) => i.amount > 0 || i.note);

  const groups = [
    { key: 'needs', label: 'Needs', color: GROUP_COLORS.needs, items: clean(needsItems), target: t.needs },
    { key: 'wants', label: 'Wants', color: GROUP_COLORS.wants, items: clean(wantsItems), target: t.wants },
    { key: 'savings', label: 'Savings & debt payoff', color: GROUP_COLORS.savings, items: clean(savingsItems), target: t.savings },
  ].map((g) => {
    const total = g.items.reduce((s, i) => s + i.amount, 0);
    return { ...g, total, pct: income ? Math.round((total / income) * 100) : 0 };
  });

  // ---------- 5. Insights ----------
  const insights = [];
  const monthlyNeeds = needsTotal;
  const efTarget = round(monthlyNeeds * (variable ? 6 : 3), 50);
  const efHave = monthlyNeeds * (EF_MONTHS[a.emergencyFund] ?? 0);
  const efMonthly = savingsItems[0].amount;

  if (shortfall > 0) {
    insights.push({
      level: 'alert',
      title: `Your essentials exceed your income by $${fmt(shortfall)}/month`,
      body: 'Before anything else, look for ways to lower fixed costs (housing, transportation, insurance) or add income. A bookkeeper can help you find where money is leaking.',
    });
  }

  const housingRatio = income ? housing / income : 0;
  if (housingRatio > 0.35) {
    insights.push({
      level: 'warn',
      title: `Housing takes ${Math.round(housingRatio * 100)}% of your income`,
      body: 'Most guidelines suggest keeping housing under 30–35%. That’s why the rest of your plan is tighter — it’s worth reviewing at your next lease or refinance.',
    });
  }

  const dti = income ? debtMin / income : 0;
  if (dti > 0.15) {
    insights.push({
      level: 'warn',
      title: `Debt payments use ${Math.round(dti * 100)}% of your take-home pay`,
      body: 'Above 15% starts to squeeze everything else. Focus extra payments on your highest-interest balance first (the avalanche method).',
    });
  }

  if (hasDebt) {
    const extra = savingsItems.find((i) => i.label === 'Extra debt payments')?.amount ?? 0;
    const withPlan = payoffMonths(debtBalance, debtMin + extra);
    const minsOnly = payoffMonths(debtBalance, debtMin);
    insights.push({
      level: 'info',
      title: `Debt-free in ${fmtMonths(withPlan)}`,
      body:
        `Paying $${fmt(round(debtMin + extra))}/month toward your $${fmt(debtBalance)} balance` +
        (minsOnly !== withPlan ? ` instead of ${minsOnly == null ? 'only the minimums (which may never pay it off)' : `${fmtMonths(minsOnly)} on minimums alone`}.` : '.') +
        ' Estimate assumes ~20% APR.',
    });
  }

  if (efHave < efTarget && efMonthly > 0) {
    const months = Math.ceil((efTarget - efHave) / efMonthly);
    insights.push({
      level: 'info',
      title: `Safety net goal: $${fmt(efTarget)}`,
      body: `That’s ${variable ? 'six' : 'three'} months of essentials. At $${fmt(round(efMonthly))}/month you’ll get there in ${fmtMonths(months)}. Keep it in a high-yield savings account.`,
    });
  }

  if (variable) {
    insights.push({
      level: 'tip',
      title: 'Budget on your lowest month',
      body: 'With variable income, base this plan on a lean month. In bigger months, send the extra straight to savings or debt.',
    });
  }

  if (a.business === 'yes' || a.incomeType === 'self') {
    insights.push({
      level: 'tip',
      title: 'Keep business and personal money separate',
      body: 'Use a dedicated business account, set aside 25–30% of business profit for taxes, and pay yourself a set amount each month. Clean books make every budget easier.',
      cta: true,
    });
  } else if (a.business === 'planning') {
    insights.push({
      level: 'tip',
      title: 'Starting a business? Set up the books on day one',
      body: 'Opening a separate account and tracking expenses from the start saves hours (and missed deductions) at tax time.',
      cta: true,
    });
  }

  if (a.tracking === 'none' || a.tracking === 'loose') {
    insights.push({
      level: 'tip',
      title: 'Check in for 15 minutes every week',
      body: 'A plan only works if you compare it to what actually happened. A weekly check-in is the single habit that makes budgets stick.',
    });
  }

  return {
    income,
    targets: t,
    adjustments,
    groups,
    insights,
    shortfall,
    goalLabel: GOAL_LABELS[a.goal] ?? '',
    unassigned: Math.max(0, round(income - groups.reduce((s, g) => s + g.total, 0))),
  };
}

export const fmt = (n) => Math.round(n).toLocaleString('en-US');
