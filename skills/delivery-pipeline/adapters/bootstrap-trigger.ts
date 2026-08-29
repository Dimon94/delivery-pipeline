import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

const ADAPTER_ID = "delivery-pipeline/bootstrap-slice";
const EVIDENCE_VERSION = "1";
const ENTRY_TYPE = "delivery-pipeline-bootstrap";
const TOOL_NAME = "bootstrap_check";
const GEARSHIFT = {
  discover: "gearshift:discover-adapters:v1",
  register: "gearshift:adapter-register:v1",
  armed: "gearshift:armed:v1",
  ready: "gearshift:ready:v1",
  shifted: "gearshift:shifted:v1",
  blocked: "gearshift:blocked:v1",
  cancelled: "gearshift:cancelled:v1",
};

const CHECK_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["phase", "command"],
  properties: {
    phase: { type: "string", enum: ["red", "green"] },
    command: { type: "string", minLength: 1, maxLength: 2000 },
    ownerPaths: {
      type: "array",
      maxItems: 50,
      items: { type: "string", minLength: 1, maxLength: 500 },
    },
    remainingWork: { type: "string", minLength: 1, maxLength: 4000 },
    evidenceRefs: {
      type: "array",
      maxItems: 20,
      items: { type: "string", minLength: 1, maxLength: 1000 },
    },
  },
};

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function outputTail(result) {
  const text = [result.stdout, result.stderr].filter(Boolean).join("\n");
  return text.length <= 8000 ? text : `[output truncated]\n${text.slice(-8000)}`;
}

function escapesRoot(local) {
  return local === ".." || local.startsWith(`..${sep}`) || isAbsolute(local);
}

function repoPath(cwd, value) {
  const absolute = resolve(cwd, value);
  const local = relative(cwd, absolute);
  if (!local || local === "." || escapesRoot(local) || resolve(cwd, local) !== absolute) {
    throw new Error(`Bootstrap owner path is outside the Execution Worktree: ${value}`);
  }
  return local.replaceAll("\\", "/");
}

async function nearestExistingAncestor(value) {
  let candidate = value;
  while (true) {
    try {
      return await realpath(candidate);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
      const parent = dirname(candidate);
      if (parent === candidate) throw error;
      candidate = parent;
    }
  }
}

function assertResolvedInside(root, actual, local) {
  if (actual === root) return;
  const actualLocal = relative(root, actual);
  if (!actualLocal || actualLocal === "." || escapesRoot(actualLocal) || resolve(root, actualLocal) !== actual) {
    throw new Error(`Bootstrap owner path resolves outside the Execution Worktree: ${local}`);
  }
}

async function fileDigest(cwd, local) {
  const root = await realpath(cwd);
  const absolute = resolve(cwd, local);
  let actual;
  try {
    actual = await realpath(absolute);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    const ancestor = await nearestExistingAncestor(dirname(absolute));
    assertResolvedInside(root, ancestor, local);
    return "absent";
  }
  assertResolvedInside(root, actual, local);
  try {
    return sha256(await readFile(absolute));
  } catch (error) {
    if (error?.code === "ENOENT") return "absent";
    throw error;
  }
}

function initialState() {
  return undefined;
}

function applyEvent(state, event) {
  if (!event || typeof event !== "object" || typeof event.kind !== "string" || typeof event.shiftId !== "string") {
    throw new Error("Invalid Bootstrap Adapter state entry");
  }
  if (event.kind === "armed") {
    if (state && state.shiftId !== event.shiftId) {
      throw new Error(`Cannot replace Bootstrap Shift ${state.shiftId} with ${event.shiftId}`);
    }
    if (typeof event.sourceModel !== "string" || typeof event.targetModel !== "string") {
      throw new Error("Bootstrap armed entry requires Source and Target Models");
    }
    return {
      shiftId: event.shiftId,
      sourceModel: event.sourceModel,
      targetModel: event.targetModel,
      phase: "armed",
      mutations: new Map(),
    };
  }
  if (!state || event.shiftId !== state.shiftId) return state;
  if (event.kind === "red") {
    if (state.phase !== "armed") throw new Error(`Invalid Bootstrap transition: ${state.phase} -> red`);
    return { ...state, phase: "red", commandHash: event.commandHash, redExitCode: event.exitCode };
  }
  if (event.kind === "mutation") {
    if (state.phase !== "red") throw new Error(`Invalid Bootstrap mutation in phase ${state.phase}`);
    if (
      typeof event.path !== "string" ||
      typeof event.beforeDigest !== "string" ||
      typeof event.afterDigest !== "string" ||
      event.beforeDigest === event.afterDigest
    ) {
      throw new Error("Invalid Bootstrap mutation evidence");
    }
    const mutations = new Map(state.mutations);
    const prior = mutations.get(event.path);
    const baseline = prior?.baseline ?? event.beforeDigest;
    if (event.afterDigest === baseline) mutations.delete(event.path);
    else mutations.set(event.path, { baseline, current: event.afterDigest });
    return { ...state, mutations };
  }
  if (event.kind === "green") {
    if (state.phase !== "red") throw new Error(`Invalid Bootstrap transition: ${state.phase} -> green`);
    return { ...state, phase: "green", readyEvidence: event.readyEvidence };
  }
  if (event.kind === "terminal") return { ...state, phase: "terminal", terminal: event.terminal };
  throw new Error(`Unknown Bootstrap Adapter event: ${event.kind}`);
}

export default function bootstrapTriggerAdapter(pi) {
  let state = initialState();
  let sessionStarted = false;
  let stateValid = true;
  const pendingArmed = [];
  const pendingTerminal = [];
  const pendingMutations = new Map();

  function append(event) {
    const next = applyEvent(state, event);
    pi.appendEntry(ENTRY_TYPE, event);
    state = next;
  }

  function updateTool() {
    const active = pi.getActiveTools().filter((name) => name !== TOOL_NAME);
    if (stateValid && state && (state.phase === "armed" || state.phase === "red")) active.push(TOOL_NAME);
    pi.setActiveTools([...new Set(active)]);
  }

  function emitRegistration() {
    pi.events.emit(GEARSHIFT.register, {
      adapterId: ADAPTER_ID,
      label: "Delivery Pipeline Bootstrap Checkpoint",
      evidenceVersion: EVIDENCE_VERSION,
      evidenceClass: "adapter-verified",
    });
  }

  function emitReady() {
    if (!state || state.phase !== "green" || !state.readyEvidence) return;
    pi.events.emit(GEARSHIFT.ready, {
      shiftId: state.shiftId,
      adapterId: ADAPTER_ID,
      evidenceVersion: EVIDENCE_VERSION,
      evidence: state.readyEvidence,
    });
  }

  function handleArmed(event) {
    if (!event || event.adapterId !== ADAPTER_ID || typeof event.shiftId !== "string") return;
    if (!sessionStarted) {
      pendingArmed.push(event);
      return;
    }
    if (state?.shiftId === event.shiftId) {
      if (event.restored !== true) {
        throw new Error(`Bootstrap Armed replay for ${event.shiftId} requires restored=true`);
      }
      if (event.sourceModel !== state.sourceModel || event.targetModel !== state.targetModel) {
        throw new Error(`Bootstrap Armed replay for ${event.shiftId} changed the immutable route`);
      }
      updateTool();
      if (state.phase === "green") emitReady();
      return;
    }
    append({
      kind: "armed",
      shiftId: event.shiftId,
      sourceModel: event.sourceModel,
      targetModel: event.targetModel,
      at: new Date().toISOString(),
    });
    updateTool();
  }

  function handleTerminal(event, terminal) {
    if (!event || event.adapterId !== ADAPTER_ID || typeof event.shiftId !== "string") return;
    if (!sessionStarted) {
      pendingTerminal.push([event, terminal]);
      return;
    }
    if (!state || state.shiftId !== event.shiftId || state.phase === "terminal") return;
    append({ kind: "terminal", shiftId: event.shiftId, terminal, at: new Date().toISOString() });
    updateTool();
  }

  pi.registerTool({
    name: TOOL_NAME,
    label: "Bootstrap Check",
    description:
      "Run the same focused check before and after the first canonical-owner change. Red must fail; green must pass and name remaining work.",
    parameters: CHECK_SCHEMA,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!stateValid) throw new Error("Bootstrap Adapter state replay failed");
      if (!state || state.phase === "terminal") throw new Error("No active Delivery Pipeline Bootstrap Shift");
      const commandHash = sha256(params.command);
      if (params.phase === "red") {
        if (state.phase !== "armed") throw new Error(`Red check requires armed phase, got ${state.phase}`);
        const result = await pi.exec("bash", ["-lc", params.command], { cwd: ctx.cwd, signal, timeout: 300000 });
        if (result.killed) throw new Error("Red check was killed or timed out");
        if (result.code === 0) throw new Error("Red check unexpectedly passed");
        append({
          kind: "red",
          shiftId: state.shiftId,
          commandHash,
          exitCode: result.code,
          at: new Date().toISOString(),
        });
        updateTool();
        return {
          content: [{ type: "text", text: `Bootstrap red confirmed (exit ${result.code}).\n${outputTail(result)}` }],
          details: { phase: "red", shiftId: state.shiftId, commandHash, exitCode: result.code },
        };
      }

      if (state.phase !== "red") throw new Error(`Green check requires red phase, got ${state.phase}`);
      if (commandHash !== state.commandHash) throw new Error("Green check must use the exact red command");
      if (!Array.isArray(params.ownerPaths) || params.ownerPaths.length === 0) {
        throw new Error("Green check requires at least one canonical-owner path");
      }
      if (typeof params.remainingWork !== "string" || params.remainingWork.trim().length === 0) {
        throw new Error("Green check requires meaningful remaining work");
      }
      const ownerPaths = params.ownerPaths.map((path) => repoPath(ctx.cwd, path));
      const verifiedOwners = [];
      for (const path of ownerPaths) {
        const mutation = state.mutations.get(path);
        if (!mutation) continue;
        const current = await fileDigest(ctx.cwd, path);
        if (current === mutation.current && current !== mutation.baseline) verifiedOwners.push(path);
      }
      if (verifiedOwners.length === 0) {
        throw new Error("No declared canonical-owner path retains a verified edit/write mutation after the red check");
      }
      const result = await pi.exec("bash", ["-lc", params.command], { cwd: ctx.cwd, signal, timeout: 300000 });
      if (result.killed) throw new Error("Green check was killed or timed out");
      if (result.code !== 0) throw new Error(`Green check failed with exit ${result.code}\n${outputTail(result)}`);
      const preservedOwners = [];
      for (const path of verifiedOwners) {
        const mutation = state.mutations.get(path);
        if (!mutation) continue;
        const current = await fileDigest(ctx.cwd, path);
        if (current === mutation.current && current !== mutation.baseline) preservedOwners.push(path);
      }
      if (preservedOwners.length === 0) {
        throw new Error("The green command did not preserve a verified canonical-owner edit/write mutation");
      }
      const readyEvidence = {
        summary: "Delivery Pipeline Bootstrap Checkpoint passed",
        evidenceRefs: [
          `gearshift-shift:${state.shiftId}`,
          `command-sha256:${commandHash}`,
          ...(params.evidenceRefs ?? []),
        ],
        verifiedEvidence: [
          `focused check observed non-zero exit ${state.redExitCode}`,
          `canonical-owner mutations after red: ${preservedOwners.slice(0, 20).join(", ")}`,
          "the same focused check exited 0",
        ],
        attestedEvidence: [`remaining work declared by Source Model: ${params.remainingWork}`],
        remainingWork: params.remainingWork,
      };
      append({
        kind: "green",
        shiftId: state.shiftId,
        readyEvidence,
        at: new Date().toISOString(),
      });
      updateTool();
      emitReady();
      return {
        content: [{ type: "text", text: `Bootstrap Checkpoint passed; Gearshift Ready emitted.\n${outputTail(result)}` }],
        details: { phase: "green", shiftId: state.shiftId, commandHash, ownerPaths: preservedOwners },
      };
    },
  });

  pi.events.on(GEARSHIFT.discover, emitRegistration);
  pi.events.on(GEARSHIFT.armed, handleArmed);
  pi.events.on(GEARSHIFT.shifted, (event) => handleTerminal(event, "shifted"));
  pi.events.on(GEARSHIFT.blocked, (event) => handleTerminal(event, "blocked"));
  pi.events.on(GEARSHIFT.cancelled, (event) => handleTerminal(event, "cancelled"));

  pi.on("tool_call", async (event, ctx) => {
    if (!stateValid || !state || state.phase !== "red") return;
    if (event.toolName !== "edit" && event.toolName !== "write") return;
    const path = event.input?.path;
    if (typeof path !== "string") return;
    const local = repoPath(ctx.cwd, path);
    pendingMutations.set(event.toolCallId, {
      shiftId: state.shiftId,
      path: local,
      beforeDigest: await fileDigest(ctx.cwd, local),
    });
  });

  pi.on("tool_result", async (event, ctx) => {
    const pending = pendingMutations.get(event.toolCallId);
    if (!pending) return;
    pendingMutations.delete(event.toolCallId);
    if (event.isError || !stateValid || !state || state.phase !== "red" || state.shiftId !== pending.shiftId) return;
    const afterDigest = await fileDigest(ctx.cwd, pending.path);
    if (afterDigest === pending.beforeDigest) return;
    append({
      kind: "mutation",
      shiftId: state.shiftId,
      path: pending.path,
      beforeDigest: pending.beforeDigest,
      afterDigest,
      at: new Date().toISOString(),
    });
  });

  pi.on("session_start", async (_event, ctx) => {
    state = initialState();
    stateValid = true;
    try {
      for (const entry of ctx.sessionManager.getBranch()) {
        if (entry.type === "custom" && entry.customType === ENTRY_TYPE) state = applyEvent(state, entry.data);
      }
    } catch (error) {
      state = initialState();
      stateValid = false;
      ctx.ui.notify(`Bootstrap Adapter state replay failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
    sessionStarted = true;
    for (const event of pendingArmed.splice(0)) handleArmed(event);
    for (const [event, terminal] of pendingTerminal.splice(0)) handleTerminal(event, terminal);
    updateTool();
  });

  pi.on("session_shutdown", async () => {
    sessionStarted = false;
    pendingMutations.clear();
    state = initialState();
  });
}
