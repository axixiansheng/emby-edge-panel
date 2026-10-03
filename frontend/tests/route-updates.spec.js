import { test, expect } from '@playwright/test';

async function enter(page) {
  await page.goto('/');
  await page.locator('[name=username]').fill('Tester1');
  await page.locator('[name=password]').fill('test-user');
  await page.getByRole('button', { name: '进入我的空间' }).click();
  await expect(page.getByRole('heading', { name: '我的线路', exact: true })).toBeVisible();
  const notice = page.getByRole('dialog', { name: '系统公告' });
  if (await notice.count()) {
    await expect(notice.getByRole('button', { name: '我已知晓', exact: true })).toBeEnabled();
    await notice.getByRole('button', { name: '我已知晓', exact: true }).click();
  }
}

test('admin updates reach owner while search is focused and editor is open', async ({
  page,
  browser,
}) => {
  test.setTimeout(120000);
  await enter(page);
  const admin = await browser.newContext();
  try {
    const headers = { Origin: 'http://127.0.0.1:18767' };
    await admin.request.post('/api/login', {
      data: { username: 'admin', password: 'test-admin' },
      headers,
    });
    const data = await (await admin.request.get('/api/admin/data')).json();
    const route = data.routes.find((r) => r.subdomain === 'tester1-secondary');
    // Other fixture tests restore data and intentionally reset node health.
    await expect
      .poll(
        async () => {
          const current = await (await admin.request.get('/api/admin/data')).json();
          return current.nodes.find((n) => n.id === route.node_id)?.online;
        },
        { timeout: 65000 },
      )
      .toBe(1);
    const search = page.getByRole('searchbox', { name: '搜索线路' });
    await search.fill('tester1-secondary');
    const result = await admin.request.post('/api/admin/update_route', {
      data: { id: route.id, target: 'https://8.8.8.8:19001' },
      headers,
    });
    expect(result.status()).toBe(202);
    await expect(page.locator('.route-tile')).toContainText(':19001', { timeout: 8000 });
    await expect(search).toBeFocused();
    await search.fill('');
    const main = page.locator('.route-tile').filter({ hasText: 'tester1-main' });
    await main.getByRole('button', { name: '修改线路' }).click();
    const target = page.getByRole('dialog').locator('[name=target]');
    await target.fill('https://8.8.8.8:19002');
    await admin.request.post('/api/admin/update_route', {
      data: { id: route.id, target: 'https://8.8.8.8:19003' },
      headers,
    });
    await expect(
      page.locator('.route-tile').filter({ hasText: 'tester1-secondary' }),
    ).toContainText(':19003', { timeout: 8000 });
    await expect(target).toHaveValue('https://8.8.8.8:19002');
    await page.keyboard.press('Escape');
    await page.getByRole('tab', { name: '任务', exact: true }).click();
    const task = page.locator('.task-row').filter({ hasText: 'tester1-secondary' }).first();
    await expect(task).toContainText('已完成');
    await expect(task).toContainText('配置已确认');
  } finally {
    await admin.close();
  }
});

test('migration finishes quickly, permits next edit and shows cache protection on mobile', async ({
  page,
}) => {
  await enter(page);
  const route = page.locator('.route-tile').filter({ hasText: 'tester1-main' });
  await route.getByRole('button', { name: '修改线路' }).click();
  await page.locator('[name=node_id]').selectOption('2');
  await page.getByRole('button', { name: '保存更改' }).click();
  await expect(route).toContainText('Test node 2', { timeout: 6000 });
  await expect(route.getByRole('button', { name: '修改线路' })).toBeEnabled();
  await route.getByRole('button', { name: '修改线路' }).click();
  await page.locator('[name=target]').fill('https://8.8.8.8:19004');
  await page.getByRole('button', { name: '保存更改' }).click();
  await expect(route).toContainText(':19004');
  await expect(route.getByRole('button', { name: '修改线路' })).toBeEnabled();
  await page.getByRole('tab', { name: '任务', exact: true }).click();
  await expect(page.locator('.task-row').filter({ hasText: '缓存保护中' })).toContainText('已完成');
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath('update-tasks-' + width + '.png') });
  }
});
