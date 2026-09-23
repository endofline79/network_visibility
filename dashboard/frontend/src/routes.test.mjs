import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const temporary = mkdtempSync(join(tmpdir(), "visibility-routes-"));
let javascript;
try {
  const result = spawnSync(
    fileURLToPath(new URL("../node_modules/.bin/tsc", import.meta.url)),
    [
      fileURLToPath(new URL("./routes.ts", import.meta.url)),
      "--target",
      "es2022",
      "--module",
      "esnext",
      "--ignoreConfig",
      "--outDir",
      temporary,
    ],
  );
  if (result.status !== 0)
    throw new Error(
      result.stderr?.toString() ||
        result.stdout?.toString() ||
        "TypeScript compilation failed",
    );
  javascript = readFileSync(join(temporary, "routes.js"), "utf8");
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
const { devicesHash, dnsHash, firewallHash, overviewHash, parseHash } =
  await import(
    `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`
  );

test("summary links reload with their filters", () => {
  assert.deepEqual(
    { ...parseHash(firewallHash("1h", "block")) },
    { ...parseHash("#activity/firewall?window=1h&action=block") },
  );
  assert.equal(parseHash(dnsHash("24h", "blocked")).dnsOutcome, "blocked");
  assert.equal(parseHash(dnsHash("24h", "blocked")).dnsWindow, "24h");
  assert.equal(parseHash(devicesHash(true, "WIRELESS")).connection, "WIRELESS");
  assert.equal(parseHash(devicesHash(true, "UNKNOWN")).connection, "UNKNOWN");
  assert.equal(parseHash(devicesHash(true)).focusClients, true);
  assert.equal(parseHash(overviewHash("6h")).window, "6h");
});

test("legacy bookmarks and invalid parameters have safe defaults", () => {
  assert.equal(parseHash("#inventory").view, "inventory");
  assert.equal(parseHash("#dns").eventMode, "dns");
  assert.equal(parseHash("#jev").view, "jev");
  const route = parseHash("#activity/firewall?window=delete&action=unknown");
  assert.equal(route.window, "15m");
  assert.equal(route.action, "all");
  assert.equal(parseHash("#activity/dns?outcome=unknown").dnsOutcome, "");
  assert.equal(parseHash("#devices?connection=unknown").connection, "");
});
