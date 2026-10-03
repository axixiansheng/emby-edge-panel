import { test, expect } from '@playwright/test';

async function enter(page, admin = false) {
  await page.goto('/');
  await page.locator('[name=username]').fill(admin ? 'admin' : 'Tester1');
  await page.locator('[name=password]').fill(admin ? 'test-admin' : 'test-user');
  await page.getByRole('button', { name: '进入我的空间' }).click();
  await expect(
    page.getByRole('heading', { name: admin ? '线路管理' : '我的线路', exact: true }),
  ).toBeVisible();
}

test('announcement requires three seconds, only closes manually and returns after login', async ({
  page,
}) => {
  await page.route('**/api/user/data', async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...(await response.json()),
        announcement: '欢迎来到 Emby Edge。\n请遵守使用规则，珍惜节点资源。',
      },
    });
  });
  await page.clock.install();
  await enter(page);
  const dialog = page.getByRole('dialog', { name: '系统公告' });
  const confirm = dialog.getByRole('button', { name: '我已知晓', exact: true });
  await expect(dialog).toContainText('请遵守使用规则');
  await expect(confirm).toBeDisabled();
  await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  await page.mouse.click(5, 5);
  await expect(dialog).toBeVisible();
  await page.clock.runFor(2000);
  await expect(confirm).toBeDisabled();
  await page.screenshot({ path: test.info().outputPath('announcement-desktop.png') });
  await page.clock.runFor(1100);
  await expect(confirm).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => (document.documentElement.dataset.theme = 'dark'));
  await page.screenshot({ path: test.info().outputPath('announcement-mobile-dark.png') });
  await page.mouse.click(5, 5);
  await expect(dialog).toBeVisible();
  await confirm.click();
  await expect(dialog).toHaveCount(0);
  await page.clock.runFor(6000);
  await expect(dialog).toHaveCount(0);
  await page.getByRole('tab', { name: '任务', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.locator('.profile-menu summary').click();
  await page.getByRole('button', { name: '退出登录' }).click();
  await enter(page);
  await expect(dialog).toBeVisible();
  await expect(confirm).toBeDisabled();
  await page.clock.runFor(3100);
  await expect(confirm).toBeEnabled();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await expect(dialog).toBeVisible();
  await expect(confirm).toBeDisabled();
});

test('announcement fits long text in light desktop and dark phone, without HTML execution', async ({
  page,
}) => {
  const content =
    '公告正文\n' +
    ('请留意线路状态。' + 'https://example.com/' + 'x'.repeat(180) + '\n').repeat(35) +
    '<img src=x onerror="window.noticeInjected=1">';
  await page.route('**/api/user/data', async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), announcement: content } });
  });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await enter(page);
  const dialog = page.getByRole('dialog', { name: '系统公告' });
  await expect(dialog).toBeVisible();
  for (const [width, height, dark] of [
    [1440, 960, false],
    [390, 844, true],
    [320, 568, true],
    [844, 390, false],
  ]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(
      (dark) => (document.documentElement.dataset.theme = dark ? 'dark' : 'light'),
      dark,
    );
    const box = await dialog.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    expect(box.y + box.height).toBeLessThanOrEqual(height);
    await expect(dialog.getByRole('button', { name: '我已知晓', exact: true })).toBeVisible();
    expect(
      await page.locator('.notice-body').evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    ).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  expect(await page.evaluate(() => window.noticeInjected)).toBeUndefined();
  await expect(dialog.locator('img')).toHaveCount(0);
});

test('blank announcement is skipped and administrators are not interrupted', async ({ page }) => {
  await page.route('**/api/user/data', async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), announcement: ' \n  ' } });
  });
  await enter(page);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.locator('.profile-menu summary').click();
  await page.getByRole('button', { name: '退出登录' }).click();
  await enter(page, true);
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('real actions renew at most once per interval; background refresh never renews', async ({
  page,
}) => {
  await page.clock.install();
  let activities = 0;
  page.on('request', (r) => {
    if (r.url().endsWith('/api/session/activity')) activities++;
  });
  await enter(page, true);
  await page.clock.runFor(20000);
  expect(activities).toBe(0);
  await page.getByRole('tab', { name: '用户', exact: true }).click();
  await page.clock.runFor(100);
  await expect.poll(() => activities).toBe(1);
  await page.getByRole('searchbox', { name: '搜索用户' }).fill('Tester');
  await page.keyboard.type('1');
  await page.clock.runFor(1000);
  expect(activities).toBe(1);
  await page.clock.runFor(15000);
  await expect.poll(() => activities).toBe(2);
  await page.clock.runFor(30000);
  expect(activities).toBe(2);
});

test('idle session locks the page even when polling is suspended by a form', async ({ page }) => {
  await page.clock.install();
  await enter(page, true);
  await page.getByRole('tab', { name: '用户', exact: true }).click();
  await page.getByRole('searchbox', { name: '搜索用户' }).focus();
  await page.clock.runFor(16000);
  await page.route('**/api/session', (route) => route.fulfill({ json: { role: null } }));
  await page.clock.fastForward(3601000);
  await expect(page.getByRole('button', { name: '进入我的空间' })).toBeVisible();
  await expect(page.locator('.workspace')).toHaveCount(0);
  await expect(page.getByRole('alert')).toContainText('登录状态已过期');
});

test('a sibling tab can extend the shared cookie without background renewal', async ({
  page,
  context,
}) => {
  await page.clock.install();
  await enter(page, true);
  const other = await context.newPage();
  await other.goto('/');
  await expect(other.getByRole('heading', { name: '线路管理', exact: true })).toBeVisible();
  await other.getByRole('tab', { name: '用户', exact: true }).click();
  await expect
    .poll(async () => (await context.cookies()).find((c) => c.name === 'emby_session')?.httpOnly)
    .toBe(true);
  await page.getByRole('tab', { name: '用户', exact: true }).click();
  await page.getByRole('searchbox', { name: '搜索用户' }).focus();
  await page.clock.runFor(16000);
  await page.clock.fastForward(3601000);
  await expect(page.getByRole('heading', { name: '用户管理', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '进入我的空间' })).toHaveCount(0);
  await other.close();
});
