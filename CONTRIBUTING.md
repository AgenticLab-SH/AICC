# Contributing

Use Node.js 20 or newer and Python 3.11 or newer. Keep all examples generic and
all personal state outside the repository.

```bash
npm run check
npm test
npm run smoke
npm run test:account-manager
```

Do not run live account switching or provider stop commands as part of tests.
Use fixture homes and fake command runners for state-changing behavior.
