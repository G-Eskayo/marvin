// Shared site data: identity (site.config.json), navigation, the feature list (features.yaml) and the dated facts.
// Everything a page says about status or numbers comes through here, so nothing is typed twice.
import { readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';
import config from '../../site.config.json';
import featuresRaw from '../data/features.yaml?raw';
import factsJson from '../data/facts.json';

export const SITE = config;
export const REPO_URL = `https://github.com/${config.repo}`;
export const blob = (path: string) => `${REPO_URL}/blob/main/${path.replace(/\/$/, '')}`;
export const tree = (path: string) => `${REPO_URL}/tree/main/${path.replace(/\/$/, '')}`;
export const issue = (n: number) => `${REPO_URL}/issues/${n}`;

export const NAV = [
  { label: 'Product', href: '/' },
  { label: `Why ${config.name}`, href: '/why/' },
  { label: 'Docs', href: '/docs/' },
  { label: 'Changelog', href: '/changelog/' },
  { label: 'Roadmap', href: '/roadmap/' },
];
export const CTA = { label: 'Join the waitlist', href: '/waitlist/' };

export type Status = 'released' | 'testing' | 'progress' | 'planned' | 'retired';
export interface Feature {
  id: string;
  title: string;
  area: string;
  status: Status;
  summary: string;
  evidence?: string[];
  adrs?: string[];
  verified_on?: string;
  page?: string;
  ticket?: number;
  shipped?: string;
  why_testing?: string;
}
export interface Area {
  id: string;
  title: string;
}

const data = parse(featuresRaw) as { areas: Area[]; features: Feature[] };
export const AREAS = data.areas;
export const FEATURES = data.features.map((f) => ({
  ...f,
  verified_on: f.verified_on ? String(f.verified_on).slice(0, 10) : undefined,
  shipped: f.shipped ? String(f.shipped).slice(0, 10) : undefined,
}));

export const STATUS_LABEL: Record<Status, string> = {
  released: 'Released',
  testing: 'Built, in testing',
  progress: 'In progress',
  planned: 'Planned',
  retired: 'Retired',
};

export const pageHref = (page: string) => `/docs/features/${page}/`;

// ADR ids → files in the engine's docs/adr. Two files can share a number (0080), so an id may carry the start of the
// slug ("0080-the-work-loop") to pick one.
const ADR_DIR = resolve(process.cwd(), '..', 'docs', 'adr');
let adrFiles: string[] = [];
try {
  adrFiles = readdirSync(ADR_DIR).filter((f) => /^\d{4}-.*\.md$/.test(f));
} catch {
  adrFiles = [];
}
export const ADR_COUNT = adrFiles.length;
export const adrLinks = (id: string) =>
  adrFiles
    .filter((f) => (id.length === 4 ? f.startsWith(`${id}-`) : f.startsWith(id)))
    .map((f) => ({ id: id.slice(0, 4), file: f, href: blob(`docs/adr/${f}`), title: f.replace(/^\d{4}-/, '').replace(/\.md$/, '').replace(/-/g, ' ') }));

export const evidenceHref = (e: string) => (/^https?:/.test(e) ? e : e.endsWith('/') ? tree(e) : blob(e));
export const evidenceLabel = (e: string) => {
  const pr = e.match(/\/pull\/(\d+)$/);
  return pr ? `PR #${pr[1]}` : e;
};

export interface Fact {
  id: string;
  value: string;
  label: string;
  detail: string;
  command: string;
}
export const FACTS = factsJson as { counted_on: string; items: Fact[] };
export const fact = (id: string) => FACTS.items.find((f) => f.id === id)!;

export const fmtDate = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
