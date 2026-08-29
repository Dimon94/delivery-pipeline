# ADR-0007: Keep Pi Gearshift optional and Adapter-owned

**Status:** Accepted
**Date:** 2026-08-29
**Decider:** User (Dimon)

Delivery Pipeline version 3 may start eligible pi frontend/backend lanes on a configured bootstrap model and use the separately installed Pi Gearshift package to shift to the role's ordinary model only after the Delivery Pipeline Bootstrap Adapter proves its Bootstrap Checkpoint. Gearshift stays `off`, per-ticket `opt_in`, or `all_eligible` by one configuration mode; the Adapter remains co-located with Delivery Pipeline and is loaded only for eligible lanes, so the canonical multi-runtime core keeps Codex/Claude behavior unchanged and the generic Gearshift package never owns tracker, TDD, ticket, Herdr, or Review semantics.

This ADR supersedes ADR-0004 only for the version 2 model-role schema: version 3 adds the Gearshift policy and optional pi frontend/backend bootstrap route. ADR-0004's config-driven runtime routing, current-calling-session coordinator, strict validation, and no-fallback decisions remain in force. Bootstrap Handoff stays inside one Worker lane and never replaces fresh-context Final Review or remote publication authority.
