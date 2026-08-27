import { test, expect, clickNavLink, openSidebarSection } from './fixtures';

test.describe('Sidebar', () => {
  // 1. Sidebar visible on desktop
  test('sidebar is visible on desktop viewport', async ({ authedPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(page.locator('.sidebar')).toBeVisible();
  });

  // 2. Active link highlighted
  test('active nav link is highlighted on current route', async ({ authedPage: page }) => {
    await page.goto('/invoices');
    await expect(page.locator('.sidebar__link--active[href="/invoices"]')).toBeVisible();
  });

  // 3. All top-level rail rows present.
  //    The rail is two-level now: plain links top and bottom, four disclosure
  //    sections in between. The old flat `.sidebar__group-label` headings are
  //    gone from the nav entirely — the only one left in the sidebar is the FY
  //    switcher's, which test 5 covers.
  test('sidebar renders every top-level row', async ({ authedPage: page }) => {
    const nav = page.locator('.sidebar__nav');
    await expect(nav.locator('a.sidebar__link[href="/"]')).toBeVisible();
    await expect(nav.locator('a.sidebar__link[href="/ledgers"]')).toBeVisible();

    for (const id of ['sales', 'catalogue', 'reports', 'marketplace']) {
      await expect(
        nav.locator(`.sidebar__section-toggle[aria-controls="nav-section-${id}"]`),
      ).toBeVisible();
    }

    await expect(page.locator('.sidebar__nav .sidebar__group-label')).toHaveCount(0);
  });

  // 4. User email visible in footer
  test('sidebar footer shows user email', async ({ authedPage: page }) => {
    await expect(page.locator('.sidebar__user-email')).toBeVisible();
    const email = await page.locator('.sidebar__user-email').textContent();
    expect(email?.trim().length).toBeGreaterThan(0);
  });

  // 5. FY switcher in sidebar
  test('FY switcher section visible in sidebar', async ({ authedPage: page }) => {
    // Both switchers live in .sidebar__fy and both are listbox buttons, so the
    // old unscoped `button[aria-haspopup="listbox"]` matched two elements and
    // failed strict mode. Their accessible names are the selected company and
    // financial year, which are data — assert on the pair instead.
    const switchers = page.locator('.sidebar__fy button[aria-haspopup="listbox"]');
    await expect(page.locator('.sidebar__fy').getByText('Financial Year')).toBeVisible();
    await expect(switchers).toHaveCount(2);
    await expect(switchers.first()).toBeVisible();
    await expect(switchers.last()).toBeVisible();
  });

  // 6. Sidebar persists across page navigation
  test('sidebar stays visible when navigating between pages', async ({ authedPage: page }) => {
    await clickNavLink(page, '/catalogue');
    await expect(page.locator('.sidebar')).toBeVisible();
    await clickNavLink(page, '/invoices');
    await expect(page.locator('.sidebar')).toBeVisible();
  });

  // 7. Desktop collapse rail
  test('collapse toggle puts the shell into rail mode', async ({ authedPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(page.locator('.app-shell')).not.toHaveClass(/app-shell--rail/);

    await page.click('.sidebar__collapse');
    await expect(page.locator('.app-shell')).toHaveClass(/app-shell--rail/);

    await page.click('.sidebar__collapse');
    await expect(page.locator('.app-shell')).not.toHaveClass(/app-shell--rail/);
  });

  test('rail state survives a reload', async ({ authedPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.click('.sidebar__collapse');
    await expect(page.locator('.app-shell')).toHaveClass(/app-shell--rail/);

    await page.reload();
    await expect(page.locator('.app-shell')).toHaveClass(/app-shell--rail/);
  });

  test('nav links keep accessible names in rail mode', async ({ authedPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.click('.sidebar__collapse');
    const sidebar = page.locator('.sidebar');

    // Labels are clipped, not removed — they must stay reachable by name. At
    // 68px a section is one link standing in for the whole section, so what it
    // announces is the section ("Sales"), not the page it happens to open.
    await expect(sidebar.getByRole('link', { name: 'Overview' })).toBeAttached();
    await expect(sidebar.getByRole('link', { name: 'Sales' })).toBeAttached();
    await expect(sidebar.getByRole('link', { name: 'Settings' })).toBeAttached();

    // …and that stand-in link is the one that actually goes somewhere.
    await expect(sidebar.getByRole('link', { name: 'Sales' })).toHaveAttribute(
      'href',
      '/invoices',
    );
  });

  test('collapse toggle is hidden on mobile', async ({ authedPage: page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('.sidebar__collapse')).toBeHidden();
  });
});

/**
 * The two-level rail.
 *
 * Every one of these is about the disclosure behaviour rather than about any
 * one page, which is why they assert on aria-expanded and on the presence of
 * `#nav-section-*` rather than on headings: a section's children are removed
 * from the DOM when it closes, so "is this link reachable" is a real question
 * now and specs elsewhere depend on the answer (see clickNavLink in fixtures).
 */
test.describe('Sidebar sections', () => {
  const toggle = (page: import('@playwright/test').Page, id: string) =>
    page.locator(`.sidebar__section-toggle[aria-controls="nav-section-${id}"]`);

  test('a section toggle expands and collapses its children', async ({
    authedPage: page,
  }) => {
    // Catalogue is closed on a fresh session — 'sales' is the default.
    const catalogue = toggle(page, 'catalogue');
    await expect(catalogue).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('#nav-section-catalogue')).toBeHidden();

    await catalogue.click();
    await expect(catalogue).toHaveAttribute('aria-expanded', 'true');
    await expect(
      page.locator('#nav-section-catalogue a.sidebar__link--child[href="/catalogue"]'),
    ).toBeVisible();
    // Products, Inventory and Products & Inventory collapsed into one entry,
    // so the section is down to two children.
    await expect(
      page.locator('#nav-section-catalogue a.sidebar__link--child'),
    ).toHaveCount(2);

    await catalogue.click();
    await expect(catalogue).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('#nav-section-catalogue')).toBeHidden();
  });

  test('opening a section closes the one that was open', async ({ authedPage: page }) => {
    // The accordion is the whole point of the redesign: it is what keeps the
    // rail to roughly ten rows however many pages get added to a section.
    await expect(toggle(page, 'sales')).toHaveAttribute('aria-expanded', 'true');

    await toggle(page, 'reports').click();

    await expect(toggle(page, 'reports')).toHaveAttribute('aria-expanded', 'true');
    await expect(toggle(page, 'sales')).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('#nav-section-sales')).toBeHidden();
  });

  test('navigating into a section opens it', async ({ authedPage: page }) => {
    // Arriving by URL (a bookmark, a redirect, a keyboard shortcut) has to
    // open the owning section, otherwise the current page has no visible
    // entry in the rail at all.
    await page.goto('/day-book');

    await expect(toggle(page, 'reports')).toHaveAttribute('aria-expanded', 'true');
    await expect(
      page.locator('#nav-section-reports a.sidebar__link--active[href="/day-book"]'),
    ).toBeVisible();
    await expect(toggle(page, 'sales')).toHaveAttribute('aria-expanded', 'false');
  });

  test('the open section survives a reload', async ({ authedPage: page }) => {
    // Opened by hand while sitting on '/', which owns no section — so this
    // asserts the persisted choice, not the route auto-opening it again.
    await openSidebarSection(page, 'marketplace');
    await expect(page).toHaveURL('/');

    await page.reload();
    await expect(toggle(page, 'marketplace')).toHaveAttribute('aria-expanded', 'true');
    await expect(toggle(page, 'sales')).toHaveAttribute('aria-expanded', 'false');
  });

  test('rail mode renders sections as links, not disclosures', async ({
    authedPage: page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.click('.sidebar__collapse');
    await expect(page.locator('.app-shell')).toHaveClass(/app-shell--rail/);

    // A 68px rail has nothing to expand into, so each section collapses to a
    // single link pointing at its first child (/invoices for sales).
    await expect(page.locator('.sidebar__section-toggle')).toHaveCount(0);
    await expect(
      page.locator('.sidebar a.sidebar__link--rail-section[href="/invoices"]'),
    ).toBeVisible();
  });
});
