import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

async function login(page, admin = false) {
  await page.goto('/');
  await page.locator('[name=username]').fill(admin ? 'admin' : 'Tester1');
  await page.locator('[name=password]').fill(admin ? 'test-admin' : 'test-user');
  await page.getByRole('button', { name: '进入我的空间' }).click();
  await expect(
    page.getByRole('heading', { name: admin ? '线路管理' : '我的线路', exact: true }),
  ).toBeVisible();
}
async function pixels(page) {
  return page
    .locator('canvas')
    .first()
    .evaluate((c) => {
      const gl = c.getContext('webgl2'),
        b = new Uint8Array(c.width * c.height * 4);
      gl.readPixels(0, 0, c.width, c.height, gl.RGBA, gl.UNSIGNED_BYTE, b);
      let count = 0,
        hash = 0;
      for (let i = 0; i < b.length; i += 4) {
        if (b[i + 3]) count++;
        hash = (Math.imul(hash, 31) + b[i] + b[i + 1] + b[i + 2] + b[i + 3]) >>> 0;
      }
      return { count, hash };
    });
}

test('user routes: create, edit, search, layout, copy and delete', async ({ page }) => {
  await login(page);
  await expect(page.locator('.route-tile')).toHaveCount(2);
  await page.getByRole('button', { name: '新建线路', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: '新建线路', exact: true }).click();
  await page.locator('[name=subdomain]').fill('qa');
  await page.locator('[name=target]').fill('https://8.8.8.8:8096');
  await page.getByRole('button', { name: '创建线路', exact: true }).click();
  await expect(page.locator('.route-tile').filter({ hasText: 'tester1-qa' })).toBeVisible();
  const route = page.locator('.route-tile').filter({ hasText: 'tester1-qa' });
  await expect(route.getByRole('button', { name: '修改线路' })).toBeEnabled();
  await route.getByRole('button', { name: '修改线路' }).click();
  await page.locator('[name=target]').fill('https://8.8.8.8:8920');
  await expect(page.locator('[name=node_id] option:enabled')).toHaveCount(2);
  await page.getByRole('button', { name: '保存更改' }).click();
  await expect(route).toContainText(':8920');
  await route.getByRole('button', { name: '复制入口', exact: true }).click();
  await expect(route.getByRole('button', { name: '已复制', exact: true })).toBeVisible();
  await page.getByRole('searchbox', { name: '搜索线路' }).fill('none-match');
  await expect(page.getByRole('heading', { name: '没有匹配的线路' })).toBeVisible();
  await page.getByRole('button', { name: '清除筛选' }).click();
  await page.getByRole('button', { name: '列表布局' }).click();
  await expect(page.locator('.route-table tbody tr')).toHaveCount(3);
  const row = page.locator('tr').filter({ hasText: 'tester1-qa' });
  await expect(row.getByRole('button', { name: '删除线路' })).toBeEnabled();
  await row.getByRole('button', { name: '删除线路' }).click();
  await page.getByRole('button', { name: '确认删除' }).click();
  await expect(page.locator('.route-table tbody tr')).toHaveCount(2);
  await page.getByRole('tab', { name: '任务', exact: true }).click();
  await expect(page.locator('.task-row')).toHaveCount(3);
});

test('admin quota, authorization code, registration and announcement', async ({
  page,
  browser,
}) => {
  await login(page, true);
  await page.getByRole('tab', { name: '用户', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Tester1 线路额度' }).fill('7');
  await page.getByRole('button', { name: '保存额度' }).click();
  await expect(page.getByRole('spinbutton', { name: 'Tester1 线路额度' })).toHaveValue('7');
  await page.getByRole('tab', { name: '授权码', exact: true }).click();
  await page.getByRole('button', { name: '签发授权码', exact: true }).click();
  await page.locator('[name=route_limit]').fill('4');
  await page.getByRole('dialog').getByRole('button', { name: '签发授权码' }).click();
  await expect(page.locator('.code-value')).toHaveCount(1);
  const code = await page.locator('.code-value').innerText();
  const member = await browser.newPage();
  await member.goto('/');
  await member.getByRole('tab', { name: '注册', exact: true }).click();
  await member.locator('[name=username]').fill('NewMember');
  await member.locator('[name=password]').fill('new-password');
  await member.locator('[name=code]').fill(code);
  await member.getByRole('button', { name: '创建账户' }).click();
  await expect(member.getByRole('heading', { name: '我的线路', exact: true })).toBeVisible();
  await expect(member.locator('.overview-facts')).toContainText('/ 4');
  await member.close();
  await page.getByRole('tab', { name: '公告', exact: true }).click();
  await page.locator('textarea').fill('Updated announcement');
  await page.getByRole('button', { name: '发布公告' }).click();
  await expect(page.getByRole('status')).toContainText('公告已发布');
  await page.getByRole('tab', { name: '线路', exact: true }).click();
  await expect(page.locator('.announcement')).toContainText('Updated announcement');
});

test('admin portable export and validated restore in isolated fixture', async ({ page }) => {
  await login(page, true);
  await page.getByRole('tab', { name: '备份', exact: true }).click();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出数据' }).click();
  const file = await downloaded;
  const bytes = await fs.readFile(await file.path());
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: 'backup.json', mimeType: 'application/json', buffer: bytes });
  await expect(page.getByRole('heading', { name: '恢复预览' })).toBeVisible();
  await expect(page.getByRole('button', { name: '恢复数据', exact: true })).toBeDisabled();
  await page.getByRole('checkbox', { name: '确认使用此备份覆盖当前数据' }).check();
  await page.getByRole('button', { name: '恢复数据', exact: true }).click();
  await expect(page.locator('.restore-result')).toContainText('数据已恢复');
  await expect(page.locator('.saved-backup-row')).toHaveCount(1);
  await page.locator('input[type=file]').setInputFiles({
    name: 'broken.json',
    mimeType: 'application/json',
    buffer: Buffer.from('{}'),
  });
  await expect(page.locator('.form-error')).toContainText('备份');
  await expect(page.getByRole('heading', { name: '恢复预览' })).toHaveCount(0);
});

test('all admin views fit desktop and mobile, with clean runtime', async ({ page }) => {
  const failures = [];
  page.on('pageerror', (e) => failures.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error') failures.push(m.text());
  });
  await login(page, true);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 960 });
    for (const name of ['线路', '节点', '用户', '授权码', '任务', '公告', '备份']) {
      await page.getByRole('tab', { name, exact: true }).click();
      await expect(page.getByRole('tabpanel')).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    }
  }
  expect(failures).toEqual([]);
});

test('admin adds and removes an unused node', async ({ page }) => {
  await login(page, true);
  await page.getByRole('tab', { name: '节点', exact: true }).click();
  await page.getByRole('button', { name: '添加节点', exact: true }).click();
  await page.locator('[name=name]').fill('Temporary QA node');
  await page.locator('[name=host]').fill('8.8.4.4');
  await page.locator('[name=port]').fill('54322');
  await page.locator('[name=public_port]').fill('54323');
  await page.locator('[name=key]').fill('qa-only-key');
  await page.getByRole('dialog').getByRole('button', { name: '添加节点' }).click();
  const node = page.locator('.node-tile').filter({ hasText: 'Temporary QA node' });
  await expect(node).toBeVisible();
  await node.getByRole('button', { name: '删除节点' }).click();
  await page.getByRole('button', { name: '确认删除' }).click();
  await expect(node).toHaveCount(0);
});

test('no WebGL still provides usable authentication and routes', async ({ browser }) => {
  const context = await browser.newContext();
  await context.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type, ...args) {
      return type.startsWith('webgl') ? null : original.call(this, type, ...args);
    };
  });
  const page = await context.newPage();
  await login(page);
  await expect(page.locator('.route-tile')).toHaveCount(2);
  await expect(page.locator('.scene-fallback')).toBeVisible();
  await expect(page.locator('.connection-scene.ready')).toHaveCount(0);
  await context.close();
});

test('Three.js renders, responds, animates and stops when paused', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('.connection-scene.ready canvas');
  const start = await pixels(page);
  expect(start.count).toBeGreaterThan(3000);
  await page.waitForTimeout(450);
  expect((await pixels(page)).hash).not.toBe(start.hash);
  await page.getByRole('button', { name: '暂停动效' }).click();
  await page.waitForTimeout(300);
  const paused = await pixels(page);
  await page.waitForTimeout(350);
  expect((await pixels(page)).hash).toBe(paused.hash);
  await page.mouse.move(300, 200);
  expect((await pixels(page)).hash).not.toBe(paused.hash);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(100);
  expect((await pixels(page)).count).toBeGreaterThan(1000);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('reduced motion, dark mode and logout remain usable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await login(page);
  await page.locator('.profile-menu summary').click();
  await page.getByRole('combobox', { name: '外观' }).selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect(page.getByRole('button', { name: '进入我的空间' })).toBeVisible();
  await page.waitForSelector('.connection-scene.ready canvas');
  const first = await pixels(page);
  await page.waitForTimeout(300);
  expect((await pixels(page)).hash).toBe(first.hash);
});
