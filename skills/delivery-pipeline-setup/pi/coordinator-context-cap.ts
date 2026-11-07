// Delivery-pipeline coordinator context cap for pi.
// Coordinator sessions (first user prompt starts with `$delivery-pipeline…`) compact once the
// context passes the cap; worker and ordinary sessions keep pi's default compaction.
// Install: ln -s <this file> ~/.pi/agent/extensions/dp-coordinator-context-cap.ts
// Override the cap with DP_COORDINATOR_CONTEXT_CAP (tokens).
// @ts-nocheck

const CAP = Number(process.env.DP_COORDINATOR_CONTEXT_CAP) || 150_000;
const COORDINATOR_PROMPT = /^\s*\[?\$delivery-pipeline(-[a-z0-9]+)?\b/;
const SUMMARY_FOCUS =
  "Delivery-pipeline coordinator. Keep: input artifact, current gate, map registry path, " +
  "Map Integration Worktree/branch, active lanes (lane_id, state, worktree), pending decisions " +
  "and the next action. Drop file contents, command output and already-consumed lane reports; " +
  "after compaction re-read the map registry Coordinator Recovery record.";

function text(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.map((part) => (part && part.type === "text" ? part.text : "")).join("");
}

function isCoordinator(ctx) {
  for (const entry of ctx.sessionManager.getEntries()) {
    if (entry.type !== "message" || entry.message?.role !== "user") continue;
    return COORDINATOR_PROMPT.test(text(entry.message.content));
  }
  return false;
}

export default function (pi) {
  let coordinator;
  let compacting = false;

  pi.on("turn_end", (_event, ctx) => {
    if (compacting) return;
    coordinator ??= isCoordinator(ctx) || undefined;
    if (!coordinator) return;
    const tokens = ctx.getContextUsage()?.tokens;
    if (tokens == null || tokens <= CAP) return;
    compacting = true;
    ctx.compact({
      customInstructions: SUMMARY_FOCUS,
      onComplete: () => {
        compacting = false;
      },
      onError: (error) => {
        compacting = false;
        if (ctx.hasUI) ctx.ui.notify(`coordinator compaction failed: ${error.message}`, "error");
      },
    });
  });
}
