// Рендер слайдов в PNG: node render.cjs 01-intro.html ../posts/01-intro
// Каждый <section class="slide" id="..."> сохраняется как <id>.png
// Класс overlay — прозрачный фон (слой с текстом поверх видео)
//
// Правило вёрстки: слова НИКОГДА не переносятся по частям. Мягкие переносы (&shy;) запрещены,
// а заголовок, в который длинное слово не влезает, автоматически уменьшается, пока не влезет.
// Рядом пишется texts.json — сколько слов на каждом слайде (по нему видео держит слайд дольше).
const fs = require("fs");
const path = require("path");
const { chromium } = require(path.join(require("child_process").execSync("npm root -g").toString().trim(), "playwright"));

(async () => {
  const [src, outDir] = process.argv.slice(2);
  const html = fs.readFileSync(src, "utf8");
  if (/&shy;|­/.test(html)) {
    console.error(`✗ ${src}: мягкие переносы (&shy;) запрещены — слова не должны разрываться`);
    process.exit(1);
  }
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  await page.goto("file://" + path.resolve(src));
  await page.addStyleTag({ content: "* { hyphens: manual !important; -webkit-hyphens: manual !important; overflow-wrap: normal !important; word-break: normal !important }" });
  await page.evaluate(() => document.fonts.ready);
  // уменьшаем шрифт у текста, где самое длинное слово шире строки
  const shrunk = await page.evaluate(() => {
    const log = [];
    for (const el of document.querySelectorAll("section.slide h1, section.slide h2, section.slide .h, section.slide .big, section.slide .ov-big, section.slide .what, section.slide .it span, section.slide .sub")) {
      let size = parseFloat(getComputedStyle(el).fontSize), start = size, guard = 0;
      while (el.scrollWidth > el.clientWidth + 1 && guard++ < 40) {
        size *= 0.95;
        el.style.fontSize = size + "px";
      }
      if (size < start) log.push(`${el.closest("section").id}: «${el.textContent.trim().slice(0, 30)}» ${Math.round(start)}→${Math.round(size)}px`);
    }
    return log;
  });
  shrunk.forEach((l) => console.log("  шрифт уменьшен, чтобы слово влезло —", l));
  const texts = {};
  for (const el of await page.$$("section.slide")) {
    const id = await el.getAttribute("id");
    const transparent = await el.evaluate((n) => n.classList.contains("overlay"));
    texts[id] = await el.evaluate((n) => (n.innerText.match(/[\p{L}\p{N}]+/gu) || []).length);
    await el.screenshot({ path: path.join(outDir, `${id}.png`), omitBackground: transparent });
    console.log("saved", id, `(${texts[id]} слов)`);
  }
  const tf = path.join(outDir, "texts.json");
  const old = fs.existsSync(tf) ? JSON.parse(fs.readFileSync(tf, "utf8")) : {};
  fs.writeFileSync(tf, JSON.stringify({ ...old, ...texts }, null, 1) + "\n");
  await browser.close();
})();
