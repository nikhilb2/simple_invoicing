import { defineConfig, type HeadConfig } from 'vitepress';

const SITE = 'https://guide.simpleinvoicings.com';
const SITE_NAME = 'Simple Invoicing Guide';
const OG_IMAGE = `${SITE}/og.png`;

/** `sales/invoices.md` → `/sales/invoices`, `ledgers/index.md` → `/ledgers/`, matching `cleanUrls`. */
function pageUrl(relativePath: string): string {
  const path = relativePath.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '');
  return `${SITE}/${path}`;
}

/** Tells search engines what the product is, so the guide can show as a software result. */
const SOFTWARE_JSON_LD = JSON.stringify({
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: 'Simple Invoicing',
  applicationCategory: 'BusinessApplication',
  operatingSystem: 'Web, Windows, macOS, Linux, Android, iOS',
  description:
    'Free, open-source GST billing software for Indian small businesses: GST invoices, quotations, credit notes, e-way bills, GSTR-1 JSON export, inventory, ledgers and UPI payments.',
  url: 'https://simpleinvoicings.com',
  downloadUrl: 'https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software',
  license: 'https://opensource.org/licenses/MIT',
  offers: { '@type': 'Offer', price: '0', priceCurrency: 'INR', description: 'Free to self-host' },
});

export default defineConfig({
  title: SITE_NAME,
  description: 'How to use Simple Invoicing, free and open-source GST billing software for India: GST invoices, GSTR-1, stock, ledgers and payments.',
  lang: 'en-IN',
  cleanUrls: true,
  lastUpdated: false,
  sitemap: { hostname: SITE },
  head: [
    ['link', { rel: 'icon', href: '/favicon.svg', type: 'image/svg+xml' }],
    ['meta', { property: 'og:site_name', content: SITE_NAME }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:locale', content: 'en_IN' }],
    ['meta', { property: 'og:image', content: OG_IMAGE }],
    ['meta', { property: 'og:image:width', content: '1200' }],
    ['meta', { property: 'og:image:height', content: '630' }],
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:image', content: OG_IMAGE }],
    ['script', { type: 'application/ld+json' }, SOFTWARE_JSON_LD],
  ],
  // Per-page canonical and share tags. VitePress already writes <title> and the
  // description meta from each page's frontmatter.
  transformHead({ pageData, title, description }): HeadConfig[] {
    if (pageData.isNotFound) return [['meta', { name: 'robots', content: 'noindex' }]];
    const url = pageUrl(pageData.relativePath);
    return [
      ['link', { rel: 'canonical', href: url }],
      ['meta', { property: 'og:url', content: url }],
      ['meta', { property: 'og:title', content: title }],
      ['meta', { property: 'og:description', content: description }],
      ['meta', { name: 'twitter:title', content: title }],
      ['meta', { name: 'twitter:description', content: description }],
    ];
  },
  themeConfig: {
    logo: '/favicon.svg',
    siteTitle: 'Simple Invoicing Guide',
    search: { provider: 'local' },
    outline: { level: [2, 3], label: 'On this page' },
    nav: [
      { text: 'Quick start', link: '/getting-started/' },
      { text: 'Troubleshooting', link: '/help/faq' },
      { text: 'Open the app', link: 'https://app.simpleinvoicings.com' },
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/nikhilb2/simple-invoicing-free-gst-billing-software' }],
    sidebar: [
      {
        text: 'Getting started',
        items: [
          { text: 'Quick start', link: '/getting-started/' },
          { text: 'Finding your way around', link: '/getting-started/tour' },
          { text: 'Company setup', link: '/getting-started/company-setup' },
          { text: 'Financial years', link: '/getting-started/financial-years' },
          { text: 'Companies, roles and team', link: '/getting-started/team' },
        ],
      },
      {
        text: 'Sales',
        items: [
          { text: 'Invoices', link: '/sales/invoices' },
          { text: 'Send and share', link: '/sales/sending' },
          { text: 'Invoice Feed', link: '/sales/invoice-feed' },
          { text: 'Quotations and proforma', link: '/sales/quotations' },
          { text: 'Invoice Dues', link: '/sales/dues' },
          { text: 'Credit and debit notes', link: '/sales/credit-notes' },
          { text: 'Cash and bank', link: '/sales/cash-bank' },
        ],
      },
      {
        text: 'Catalogue',
        items: [
          { text: 'Products and stock', link: '/catalogue/products' },
          { text: 'Serial numbers and IMEIs', link: '/catalogue/serials' },
          { text: 'Manufacturing', link: '/catalogue/manufacturing' },
        ],
      },
      { text: 'Ledgers', items: [{ text: 'Customers and suppliers', link: '/ledgers/' }] },
      {
        text: 'Reports and GST',
        items: [
          { text: 'Dashboard', link: '/reports/dashboard' },
          { text: 'Analytics', link: '/reports/analytics' },
          { text: 'Day Book', link: '/reports/day-book' },
          { text: 'Tax Ledger', link: '/reports/tax-ledger' },
          { text: 'GSTR-1 filing', link: '/reports/gstr1' },
          { text: 'GSTR-3B worksheet', link: '/reports/gstr3b' },
        ],
      },
      { text: 'Marketplace', items: [{ text: 'Trade surplus stock', link: '/marketplace/' }] },
      {
        text: 'Settings',
        items: [
          { text: 'Overview', link: '/settings/' },
          { text: 'Email', link: '/settings/email' },
          { text: 'Backups', link: '/settings/backups' },
        ],
      },
      {
        text: 'Integrations',
        items: [
          { text: 'AI assistants', link: '/integrations/ai-assistants' },
          { text: 'API and API keys', link: '/integrations/api' },
          { text: 'Run your own copy', link: '/integrations/self-hosting' },
        ],
      },
      {
        text: 'Help',
        items: [
          { text: 'Troubleshooting', link: '/help/faq' },
          { text: 'Glossary', link: '/help/glossary' },
        ],
      },
    ],
    docFooter: { prev: 'Previous', next: 'Next' },
    footer: { message: 'Screenshots show a made-up demo business.', copyright: 'Open source under the MIT licence.' },
  },
});
