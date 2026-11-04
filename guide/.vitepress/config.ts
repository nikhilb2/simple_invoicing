import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'Simple Invoicing Guide',
  description: 'User guide for Simple Invoicing, free GST billing and accounting software for Indian small businesses.',
  lang: 'en-IN',
  cleanUrls: true,
  lastUpdated: false,
  sitemap: { hostname: 'https://guide.simpleinvoicings.com' },
  head: [['link', { rel: 'icon', href: '/favicon.svg', type: 'image/svg+xml' }]],
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
    socialLinks: [{ icon: 'github', link: 'https://github.com/nikhilb2/simple_invoicing' }],
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
