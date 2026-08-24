import { expect, test } from '@playwright/test';

/**
 * Browser coverage for the session lifecycle: guard redirect, failed sign-in,
 * successful sign-in, sign-out.
 *
 * Requires a running stack (`uvicorn nexus.main:app --port 8000` plus the
 * dashboard dev server) and an existing account. Set both credentials to enable
 * it — without them there is nothing to sign in as, so the file skips rather
 * than fails:
 *
 *   NEXUS_E2E_EMAIL=operator@example.com NEXUS_E2E_PASSWORD='...' npx playwright test e2e/auth.spec.ts
 *
 * `E2E_BASE_URL` overrides the dashboard origin (default http://localhost:3000).
 */

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000';
const EMAIL = process.env.NEXUS_E2E_EMAIL || '';
const PASSWORD = process.env.NEXUS_E2E_PASSWORD || '';

test.describe('authentication', () => {
  test.skip(
    !EMAIL || !PASSWORD,
    'Set NEXUS_E2E_EMAIL and NEXUS_E2E_PASSWORD to run the auth flow against a live stack.'
  );

  test('an anonymous visitor is sent to the login page', async ({ page }) => {
    await page.goto(`${BASE_URL}/agents`);

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator('#login-email')).toBeVisible();
  });

  test('a wrong password is reported and does not open a session', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);

    await page.fill('#login-email', EMAIL);
    await page.fill('#login-password', 'definitely-not-the-password');
    await page.click('button[type="submit"]');

    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test('valid credentials open a session and sign-out closes it', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);

    await page.fill('#login-email', EMAIL);
    await page.fill('#login-password', PASSWORD);
    await page.click('button[type="submit"]');

    // Landing on the shell means the cookie was set and `/auth/me` answered.
    await expect(page).toHaveURL(`${BASE_URL}/`);
    const accountMenu = page.getByLabel('Account menu');
    await expect(accountMenu).toBeVisible();

    await accountMenu.click();
    await page.getByRole('button', { name: 'Sign out' }).click();

    await expect(page).toHaveURL(/\/login$/);

    // The session is gone server-side too, not just in this tab's memory.
    await page.goto(`${BASE_URL}/agents`);
    await expect(page).toHaveURL(/\/login$/);
  });
});
