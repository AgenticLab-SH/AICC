import { loadUserEnv } from './config.mjs';

if (process.argv[2] !== 'setup') loadUserEnv();
await import('./cli.mjs');
