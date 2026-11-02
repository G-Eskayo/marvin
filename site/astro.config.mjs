// The MARVIN website: marketing pages (src/pages) and docs (src/content/docs/docs) in one build (marvin#1007).
// The product name and links come from site.config.json, so a rename is one change.
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { readFileSync } from 'node:fs';

const site = JSON.parse(readFileSync(new URL('./site.config.json', import.meta.url), 'utf8'));
const repoUrl = `https://github.com/${site.repo}`;

export default defineConfig({
  site: site.url,
  trailingSlash: 'always',
  integrations: [
    starlight({
      title: site.name,
      description: site.description,
      logo: { src: './src/assets/mark.svg', alt: '' },
      favicon: '/favicon.svg',
      social: [{ icon: 'github', label: 'GitHub', href: repoUrl }],
      editLink: { baseUrl: `${repoUrl}/edit/main/site/` },
      lastUpdated: false,
      customCss: ['./src/styles/fonts.css', './src/styles/tokens.css', './src/styles/starlight.css'],
      components: {
        SocialIcons: './src/components/starlight/SocialIcons.astro',
      },
      sidebar: [
        { label: 'Start here', items: [{ label: 'How MARVIN fits together', link: '/docs/' }] },
        { label: 'Features', items: [{ autogenerate: { directory: 'docs/features' } }] },
        {
          label: 'Project',
          items: [
            { label: 'Roadmap', link: '/roadmap/' },
            { label: 'Changelog', link: '/changelog/' },
            { label: 'The map', link: '/map/' },
          ],
        },
      ],
    }),
  ],
});
