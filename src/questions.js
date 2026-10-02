// Assessment questions. `type` is 'currency' or 'choice'.
// `showIf(answers)` hides a question unless it returns true.
export const QUESTIONS = [
  {
    id: 'income',
    type: 'currency',
    required: true,
    label: 'What is your monthly take-home pay?',
    help: 'After taxes and deductions — what actually lands in your bank account each month. Include all household earners you budget with.',
  },
  {
    id: 'incomeType',
    type: 'choice',
    label: 'How steady is that income?',
    options: [
      { value: 'steady', label: 'Steady', hint: 'Same paycheck every month' },
      { value: 'variable', label: 'Varies', hint: 'Commission, tips, hourly or seasonal' },
      { value: 'self', label: 'Self-employed', hint: 'Freelance or business income' },
    ],
  },
  {
    id: 'household',
    type: 'choice',
    label: 'How many people does this budget support?',
    options: [
      { value: '1', label: 'Just me' },
      { value: '2', label: '2 people' },
      { value: '3-4', label: '3–4 people' },
      { value: '5+', label: '5 or more' },
    ],
  },
  {
    id: 'costOfLiving',
    type: 'choice',
    label: 'How would you describe the cost of living where you live?',
    options: [
      { value: 'low', label: 'Lower than average', hint: 'Rural or small town' },
      { value: 'average', label: 'About average' },
      { value: 'high', label: 'Higher than average', hint: 'Major city or expensive area' },
    ],
  },
  {
    id: 'housing',
    type: 'currency',
    label: 'What do you pay each month for housing?',
    help: 'Rent or mortgage payment, including HOA fees and property tax if they’re part of your payment.',
  },
  {
    id: 'transport',
    type: 'currency',
    label: 'What do you spend monthly on transportation?',
    help: 'Car payment, gas, auto insurance, parking, transit passes. A rough estimate is fine.',
  },
  {
    id: 'debtBalance',
    type: 'currency',
    label: 'How much non-mortgage debt do you have in total?',
    help: 'Credit cards, personal loans, student loans, medical bills. Enter 0 if none. Don’t include your car loan if you counted it above.',
  },
  {
    id: 'debtMinimums',
    type: 'currency',
    label: 'What are the combined minimum payments on that debt?',
    help: 'The total of all required monthly minimum payments.',
    showIf: (a) => Number(a.debtBalance) > 0,
  },
  {
    id: 'emergencyFund',
    type: 'choice',
    label: 'How much do you have saved for emergencies?',
    options: [
      { value: 'none', label: 'Nothing yet' },
      { value: 'under1', label: 'Less than 1 month of expenses' },
      { value: '1to3', label: '1–3 months' },
      { value: '3to6', label: '3–6 months' },
      { value: '6plus', label: 'More than 6 months' },
    ],
  },
  {
    id: 'retirement',
    type: 'choice',
    label: 'Are you already saving for retirement?',
    options: [
      { value: 'payroll', label: 'Yes, through my paycheck', hint: '401(k), 403(b), etc.' },
      { value: 'own', label: 'Yes, on my own', hint: 'IRA or brokerage' },
      { value: 'no', label: 'Not yet' },
    ],
  },
  {
    id: 'goal',
    type: 'choice',
    label: 'What is your #1 money goal right now?',
    options: [
      { value: 'debt', label: 'Pay off debt' },
      { value: 'emergency', label: 'Build a safety net' },
      { value: 'purchase', label: 'Save for something big', hint: 'Home, car, wedding, travel' },
      { value: 'retire', label: 'Invest for the future' },
      { value: 'organize', label: 'Just get organized', hint: 'Know where my money goes' },
    ],
  },
  {
    id: 'business',
    type: 'choice',
    label: 'Do you run a business or side hustle?',
    options: [
      { value: 'yes', label: 'Yes' },
      { value: 'planning', label: 'Planning to start one' },
      { value: 'no', label: 'No' },
    ],
  },
  {
    id: 'tracking',
    type: 'choice',
    label: 'How well do you track your spending today?',
    options: [
      { value: 'none', label: 'I don’t, really' },
      { value: 'loose', label: 'I check my bank app now and then' },
      { value: 'app', label: 'I use an app or spreadsheet' },
      { value: 'tight', label: 'I track every dollar' },
    ],
  },
];
