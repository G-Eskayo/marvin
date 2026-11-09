// Writes dist/CNAME, the custom domain GitHub Pages serves the site on, from site.config.json `url` (marvin#1007), so
// the domain lives in one place with the name. Runs after the build; check.mjs --dist then verifies it.
import { readFileSync, writeFileSync } from 'node:fs';
import { cnameFor } from './check.mjs';

const site = new URL('..', import.meta.url);
const cfg = JSON.parse(readFileSync(new URL('site.config.json', site), 'utf8'));
writeFileSync(new URL('dist/CNAME', site), `${cnameFor(cfg.url)}\n`);
