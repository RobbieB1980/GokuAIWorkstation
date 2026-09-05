---
name: migrate-neoforge-262
description: >-
  End-to-end migrate/convert a Forge or NeoForge mod to NeoForge 26.2.
  Use when converting jars/projects, running the Legacy Java Converter track,
  or planning a full 1.20.1+/1.21.x → 26.2 migration. Slash: /migrate-neoforge-262.
---

# Migrate → NeoForge 26.2

## Standing constraints

- Track: detected source **>= 1.20.1** → **26.2** only. Reject older jars.
- Success: destination-Java `gradlew build` → `build/libs/*.jar`.
- Prefer converter remaps + 262r over one-off patches; write fixes back.

## Loop

1. **Detect** source version (`SOURCE_PROFILE.json` / gradle / mods.toml).
2. **Attach ledger** `primer_changes_<source>-to-26.2` (nearest-older OK); do not skip intermediate deltas.
3. **Inventory** then migrate in order: skeleton → registries → blocks/items → entities → networking → rendering → data/assets → repair.
4. Before each API family edit: build/update an **evidence packet** (see `repair-failed-262-output/references/evidence-packet-template.md`).
5. Open **one** primer shard and **one** 262r shard matching the current error/API family.
6. Edit narrowly → **validate** with skill `validate-destination-build`.
7. On green family: skill `encode-262r-remap` if the fix is reusable.
8. Fresh session for the next unrelated error family when context is large.

## Delegation

Parent discovers evidence. Spawn at most one worker with the packet only.

| `subagent_type` | Role |
|---|---|
| `mc-research` | Read-only excerpts → update packet |
| `mc-fast` | Mechanical known remaps |
| `mc-code` | Default multi-file implementer |
| `mc-reviewer` | Independent check vs packet + build |

Single GPU: do not run parallel local GGUFs.  
Open `references/spawn-packet-contract.md` before spawning.

## References

- `references/migration-order.md` — stage list (open only if needed)
- `references/spawn-packet-contract.md` — required prompt fields
- `../repair-failed-262-output/references/262r-shard-index.md` — shard ids (links only)
- Knowledge paths: `.grok/rules/knowledge-sources.md`
