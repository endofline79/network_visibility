import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { backingSize, debounce, pointerIndex } from "../frontend/src/console/chartFit.js";

const root = new URL("../frontend/src/console/", import.meta.url);

const wide = backingSize(800, 220, 2);
assert.equal(wide.dpr, 2);
assert.equal(wide.width, 1600);
assert.equal(wide.height, 440);
assert.equal(wide.scaleX, 2);
assert.equal(wide.scaleY, 2);

const fractional = backingSize(100.4, 50.6, 1.25);
assert.equal(fractional.width, Math.round(100.4 * 1.25));
assert.equal(fractional.height, Math.round(50.6 * 1.25));
assert.equal(fractional.scaleX, fractional.width / 100.4);

const fallback = backingSize(40, 20, 0);
assert.equal(fallback.dpr, 1);
assert.equal(fallback.width, 40);
assert.equal(backingSize(-8, 10, 2).width, 0);

assert.equal(pointerIndex(0, 300, 13), 0);
assert.equal(pointerIndex(300, 300, 13), 12);
assert.equal(pointerIndex(-20, 300, 13), 0);
assert.equal(pointerIndex(999, 300, 13), 12);
assert.equal(pointerIndex(150, 300, 5), 2);
assert.equal(pointerIndex(10, 0, 8), 0);

let calls = 0;
const draw = debounce(() => {
  calls += 1;
}, 30);
draw();
draw();
draw();
assert.equal(calls, 0);
await new Promise((resolve) => setTimeout(resolve, 60));
assert.equal(calls, 1);

const css = readFileSync(new URL("console.css", root), "utf8");
const js = readFileSync(new URL("main.js", root), "utf8");
assert.doesNotMatch(css, /max-width:\s*1500px/);
assert.match(css, /\.rows\s*\{[^}]*overflow-x:\s*auto/s);
assert.match(css, /text-overflow:\s*ellipsis/);
assert.match(css, /@media \(max-width: 1100px\)/);
assert.match(css, /@media \(max-width: 720px\)/);
assert.match(css, /grid-template-columns:\s*repeat\(3,/);
assert.match(js, /ResizeObserver/);
assert.match(js, /devicePixelRatio/);
assert.match(js, /backingSize/);
assert.match(js, /title="/);

console.log("chart fit ok");
