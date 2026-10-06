// Рендер слайдов в PNG: node render.cjs 01-intro.html ../posts/01-intro
// Каждый <section class="slide" id="..."> сохраняется как <id>.png
// Класс overlay — прозрачный фон (слой с текстом поверх видео)
const path = require("path");
const { chromium } = require(path.join(require("child_process").execSync("npm root -g").toString().trim(), "playwright"));

(async () => {
  const [src, outDir] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  await page.goto("file://" + path.resolve(src));
  await page.evaluate(() => document.fonts.ready);
  for (const el of await page.$$("section.slide")) {
    const id = await el.getAttribute("id");
    const transparent = await el.evaluate((n) => n.classList.contains("overlay"));
    await el.screenshot({ path: path.join(outDir, `${id}.png`), omitBackground: transparent });
    console.log("saved", id);
  }
  await browser.close();
})();
