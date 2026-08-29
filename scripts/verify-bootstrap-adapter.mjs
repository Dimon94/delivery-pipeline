#!/usr/bin/env node
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const adapterPath = fileURLToPath(new URL("../skills/delivery-pipeline/adapters/bootstrap-trigger.ts", import.meta.url));
const source = await readFile(adapterPath, "utf8");
const module = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const factory = module.default;

const EVENTS = {
  discover: "gearshift:discover-adapters:v1",
  register: "gearshift:adapter-register:v1",
  armed: "gearshift:armed:v1",
  ready: "gearshift:ready:v1",
  shifted: "gearshift:shifted:v1",
};
const ENTRY_TYPE = "delivery-pipeline-bootstrap";
const INITIAL_OWNER = "export const owner = 'before';\n";
const tempRoots = [];

let passed = 0;
let failed = 0;
async function check(name, fn) {
  try {
    await fn();
    passed++;
    console.log(`  ✓ ${name}`);
  } catch (error) {
    failed++;
    console.error(`  ✗ ${name}`);
    console.error(`    ${error.stack ?? error}`);
  }
}

function makeHarness({ initialEntries = [], execResults = [], initialOwner = INITIAL_OWNER } = {}) {
  const tools = new Map();
  const events = new Map();
  const bus = new Map();
  const emitted = [];
  const appended = [];
  const entries = [...initialEntries];
  const notices = [];
  let activeTools = ["read", "bash", "edit", "write"];
  const queue = [...execResults];
  const cwd = mkdtempSync(join(tmpdir(), "delivery-bootstrap-"));
  tempRoots.push(cwd);
  mkdirSync(resolve(cwd, "src"));
  writeFileSync(resolve(cwd, "src/owner.ts"), initialOwner);
  const ctx = {
    cwd,
    sessionManager: { getBranch: () => entries },
    ui: { notify: (message, level = "info") => notices.push({ message, level }) },
  };
  const pi = {
    registerTool(definition) {
      tools.set(definition.name, definition);
      activeTools = [...new Set([...activeTools, definition.name])];
    },
    on(name, handler) {
      events.set(name, handler);
    },
    events: {
      on(name, handler) {
        const handlers = bus.get(name) ?? [];
        handlers.push(handler);
        bus.set(name, handlers);
      },
      emit(name, data) {
        emitted.push({ name, data });
        for (const handler of bus.get(name) ?? []) handler(data);
      },
    },
    appendEntry(customType, data) {
      appended.push({ customType, data });
      entries.push({ type: "custom", customType, data });
    },
    getActiveTools: () => [...activeTools],
    setActiveTools(names) {
      activeTools = [...names];
    },
    async exec(_command, _args, options) {
      assert.equal(options.cwd, cwd);
      const result = queue.shift();
      if (!result) throw new Error("Missing exec fixture");
      if (result.mutatePath) await writeFile(resolve(cwd, result.mutatePath), result.mutateContent ?? INITIAL_OWNER);
      return { stdout: "", stderr: "", killed: false, ...result };
    },
  };
  factory(pi);
  return {
    pi,
    ctx,
    tools,
    events,
    emitted,
    appended,
    entries,
    notices,
    queue,
    get activeTools() {
      return [...activeTools];
    },
    async start() {
      await events.get("session_start")({ reason: "startup" }, ctx);
    },
    arm(restored = false) {
      pi.events.emit(EVENTS.armed, {
        shiftId: "shift-1",
        profile: "bootstrap",
        adapterId: "delivery-pipeline/bootstrap-slice",
        sourceModel: "test/high",
        targetModel: "test/fast",
        restored,
      });
    },
    async tool(params) {
      return tools.get("bootstrap_check").execute("tool-1", params, undefined, undefined, ctx);
    },
    async mutation(path = "src/owner.ts", content = "export const owner = 'after';\n") {
      const toolCallId = `mutation-${appended.length}-${content.length}`;
      const event = { toolCallId, toolName: "edit", isError: false, input: { path } };
      await events.get("tool_call")(event, ctx);
      mkdirSync(dirname(resolve(cwd, path)), { recursive: true });
      await writeFile(resolve(cwd, path), content);
      await events.get("tool_result")(event, ctx);
    },
  };
}

console.log("Delivery Pipeline Bootstrap Adapter verification\n");

await check("default export is a factory and Adapter registers on discovery", async () => {
  assert.equal(typeof factory, "function");
  const h = makeHarness();
  await h.start();
  assert.ok(!h.activeTools.includes("bootstrap_check"));
  h.pi.events.emit(EVENTS.discover, { version: 1 });
  const registration = h.emitted.find((event) => event.name === EVENTS.register).data;
  assert.equal(registration.adapterId, "delivery-pipeline/bootstrap-slice");
  assert.equal(registration.evidenceVersion, "1");
});

await check("red -> owner mutation -> green emits normalized verified Ready Evidence", async () => {
  const h = makeHarness({ execResults: [{ code: 1, stderr: "expected failure" }, { code: 0, stdout: "pass" }] });
  await h.start();
  h.arm();
  assert.ok(h.activeTools.includes("bootstrap_check"));
  await h.tool({ phase: "red", command: "npm test -- owner" });
  await h.mutation("src/owner.ts");
  await h.tool({
    phase: "green",
    command: "npm test -- owner",
    ownerPaths: ["src/owner.ts"],
    remainingWork: "complete sibling call sites",
    evidenceRefs: ["ticket:#1"],
  });
  assert.ok(!h.activeTools.includes("bootstrap_check"));
  const ready = h.emitted.find((event) => event.name === EVENTS.ready).data;
  assert.equal(ready.shiftId, "shift-1");
  assert.equal(ready.evidence.summary, "Delivery Pipeline Bootstrap Checkpoint passed");
  assert.match(ready.evidence.verifiedEvidence.join("\n"), /canonical-owner mutations/);
  assert.equal(ready.evidence.remainingWork, "complete sibling call sites");
  assert.equal(h.queue.length, 0);
});

await check("red phase rejects a passing check", async () => {
  const h = makeHarness({ execResults: [{ code: 0 }] });
  await h.start();
  h.arm();
  await assert.rejects(() => h.tool({ phase: "red", command: "npm test" }), /unexpectedly passed/);
  assert.ok(!h.appended.some((entry) => entry.data.kind === "red"));
});

await check("green requires the exact command and an observed owner mutation", async () => {
  const h = makeHarness({ execResults: [{ code: 1 }] });
  await h.start();
  h.arm();
  await h.tool({ phase: "red", command: "npm test" });
  await assert.rejects(
    () =>
      h.tool({
        phase: "green",
        command: "npm test -- changed",
        ownerPaths: ["src/owner.ts"],
        remainingWork: "continue",
      }),
    /exact red command/,
  );
  await assert.rejects(
    () =>
      h.tool({
        phase: "green",
        command: "npm test",
        ownerPaths: ["src/owner.ts"],
        remainingWork: "continue",
      }),
    /No declared canonical-owner path/,
  );
});

await check("no-op and reverted writes do not satisfy owner mutation evidence", async () => {
  const h = makeHarness({ execResults: [{ code: 1 }] });
  await h.start();
  h.arm();
  await h.tool({ phase: "red", command: "npm test" });
  await h.mutation("src/owner.ts", INITIAL_OWNER);
  await assert.rejects(
    () =>
      h.tool({
        phase: "green",
        command: "npm test",
        ownerPaths: ["src/owner.ts"],
        remainingWork: "continue",
      }),
    /retains a verified edit\/write mutation/,
  );
  await h.mutation("src/owner.ts", "export const owner = 'changed';\n");
  await h.mutation("src/owner.ts", INITIAL_OWNER);
  await assert.rejects(
    () =>
      h.tool({
        phase: "green",
        command: "npm test",
        ownerPaths: ["src/owner.ts"],
        remainingWork: "continue",
      }),
    /retains a verified edit\/write mutation/,
  );
});

await check("green command cannot erase the verified owner mutation", async () => {
  const h = makeHarness({
    execResults: [
      { code: 1 },
      { code: 0, mutatePath: "src/owner.ts", mutateContent: INITIAL_OWNER },
    ],
  });
  await h.start();
  h.arm();
  await h.tool({ phase: "red", command: "npm test" });
  await h.mutation("src/owner.ts", "export const owner = 'changed';\n");
  await assert.rejects(
    () =>
      h.tool({
        phase: "green",
        command: "npm test",
        ownerPaths: ["src/owner.ts"],
        remainingWork: "continue",
      }),
    /green command did not preserve/,
  );
  assert.ok(!h.appended.some((entry) => entry.data.kind === "green"));
  assert.ok(!h.emitted.some((event) => event.name === EVENTS.ready));
});

await check("restored Armed event preserves prior red/mutation evidence", async () => {
  const first = makeHarness({ execResults: [{ code: 1 }] });
  await first.start();
  first.arm();
  await first.tool({ phase: "red", command: "npm test" });
  await first.mutation("src/owner.ts");
  const prior = first.entries.map((entry) => structuredClone(entry));

  const restored = makeHarness({
    initialEntries: prior,
    execResults: [{ code: 0 }],
    initialOwner: "export const owner = 'after';\n",
  });
  restored.arm(true);
  await restored.start();
  assert.ok(restored.activeTools.includes("bootstrap_check"));
  await restored.tool({
    phase: "green",
    command: "npm test",
    ownerPaths: ["src/owner.ts"],
    remainingWork: "continue after restore",
  });
  assert.ok(restored.emitted.some((event) => event.name === EVENTS.ready));
});

await check("same-Shift Armed replay requires restored=true and immutable route", async () => {
  const h = makeHarness();
  await h.start();
  h.arm();
  const appendedBefore = h.appended.length;
  assert.throws(
    () =>
      h.pi.events.emit(EVENTS.armed, {
        shiftId: "shift-1",
        profile: "bootstrap",
        adapterId: "delivery-pipeline/bootstrap-slice",
        sourceModel: "test/high",
        targetModel: "test/fast",
        restored: false,
      }),
    /restored=true/,
  );
  assert.throws(
    () =>
      h.pi.events.emit(EVENTS.armed, {
        shiftId: "shift-1",
        profile: "bootstrap",
        adapterId: "delivery-pipeline/bootstrap-slice",
        sourceModel: "test/high",
        targetModel: "test/other",
        restored: true,
      }),
    /immutable route/,
  );
  assert.equal(h.appended.length, appendedBefore);
});

await check("write can create a canonical-owner file under a new parent directory", async () => {
  const h = makeHarness({ execResults: [{ code: 1 }, { code: 0 }] });
  await h.start();
  h.arm();
  await h.tool({ phase: "red", command: "npm test" });
  await h.mutation("src/new-area/owner.ts", "export const owner = 'after';\n");
  await h.tool({
    phase: "green",
    command: "npm test",
    ownerPaths: ["src/new-area/owner.ts"],
    remainingWork: "continue after nested owner creation",
  });
  assert.ok(h.emitted.some((event) => event.name === EVENTS.ready));

  const outside = mkdtempSync(join(tmpdir(), "delivery-bootstrap-outside-"));
  tempRoots.push(outside);
  const escape = makeHarness({ execResults: [{ code: 1 }] });
  await escape.start();
  escape.arm();
  await escape.tool({ phase: "red", command: "npm test" });
  symlinkSync(outside, resolve(escape.ctx.cwd, "src/external"));
  await assert.rejects(() => escape.mutation("src/external/new-owner.ts"), /resolves outside the Execution Worktree/);
});

await check("owner path boundary accepts dot-dot-prefixed filenames and rejects parent traversal", async () => {
  const h = makeHarness({ execResults: [{ code: 1 }, { code: 0 }] });
  await h.start();
  h.arm();
  await h.tool({ phase: "red", command: "npm test" });
  await h.mutation("..owner.ts", "export const owner = 'after';\n");
  await h.tool({
    phase: "green",
    command: "npm test",
    ownerPaths: ["..owner.ts"],
    remainingWork: "continue after boundary proof",
  });
  assert.ok(h.emitted.some((event) => event.name === EVENTS.ready));

  const escape = makeHarness({ execResults: [{ code: 1 }] });
  await escape.start();
  escape.arm();
  await escape.tool({ phase: "red", command: "npm test" });
  await assert.rejects(() => escape.mutation("../escape-owner.ts"), /outside the Execution Worktree/);
});

await check("terminal Gearshift event disables Bootstrap tool and rejects a second Shift ID", async () => {
  const h = makeHarness();
  await h.start();
  h.arm();
  h.pi.events.emit(EVENTS.shifted, {
    shiftId: "shift-1",
    adapterId: "delivery-pipeline/bootstrap-slice",
  });
  assert.ok(!h.activeTools.includes("bootstrap_check"));
  assert.ok(h.appended.some((entry) => entry.customType === ENTRY_TYPE && entry.data.kind === "terminal"));
  const appendedBefore = h.appended.length;
  assert.throws(
    () =>
      h.pi.events.emit(EVENTS.armed, {
        shiftId: "shift-2",
        profile: "bootstrap",
        adapterId: "delivery-pipeline/bootstrap-slice",
        sourceModel: "test/high",
        targetModel: "test/fast",
        restored: false,
      }),
    /Cannot replace Bootstrap Shift/,
  );
  assert.equal(h.appended.length, appendedBefore);
  assert.ok(!h.activeTools.includes("bootstrap_check"));
});

for (const root of tempRoots) rmSync(root, { recursive: true, force: true });
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
