# Cayo Bookkeeping — Budget Planner

A lead-capture budget assessment built with React + Vite and hosted on Netlify.
Visitors answer 12–13 questions, enter their name and email (saved via **Netlify Forms**),
and then see a personalized budget plan with charts, insights, and a printable PDF.

## How it works

1. **Assessment** — income, household, cost of living, housing, transport, debt, emergency savings, retirement, goal, business, tracking habits (`src/questions.js`).
2. **Lead gate** — name, email, optional phone, and consent. Submitted to Netlify Forms with a summary of every answer so you have context for follow-up.
3. **Results** — adaptive budget (`src/budget.js`): starts from 50/30/20 and shifts targets for cost of living, variable income, debt focus, and emergency savings. Shows a donut chart, line items, debt payoff and safety-net timelines, and a booking call-to-action. "Download PDF" uses the browser's print-to-PDF.

## Customize

- `src/config.js` — business name and **booking link** (Cal.com discovery call).
- `src/questions.js` — edit question wording or options.
- `src/budget.js` — tweak percentages, grocery/utility estimates, insight rules.
- `src/styles.css` — colors are CSS variables at the top.

## Run locally

```bash
npm install
npm run dev
```

In dev mode the lead form logs to the console instead of submitting.

## Deploy to Netlify

1. Push this repo to GitHub.
2. In Netlify: **Add new site → Import an existing project → GitHub** and pick the repo.
   Build settings are read from `netlify.toml` (`npm run build`, publish `dist`).
3. In **Site configuration → Forms**, make sure **form detection is enabled**, then redeploy once.
   A form named `budget-lead` will appear.
4. Set up notifications under **Forms → Form notifications** (email, Slack, or a webhook/Zapier to your CRM).

Leads appear under **Forms → budget-lead** in the Netlify dashboard and can be exported to CSV.
