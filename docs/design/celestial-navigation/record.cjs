// Deterministic frame capture: pause every animation, seek to exact times, screenshot.
const { chromium } = require(process.env.HOME + '/.agents/dashboard/node_modules/playwright-core');
const path = require('path'), fs = require('fs');
(async () => {
  const [, , page_, outDir, fps = '25', w = '1280', h = '800'] = process.argv;
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.resolve(page_) + '?rec');
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  const total = await page.evaluate(() => window.BOOT_TOTAL);
  const step = 1000 / +fps; let i = 0;
  for (let t = 0; t <= total; t += step, i++) {
    await page.evaluate(ms => window.seek(ms), t);
    await page.screenshot({ path: `${outDir}/f${String(i).padStart(4, '0')}.png` });
  }
  console.log(`${i} frames, ${total}ms`);
  await browser.close();
})();
