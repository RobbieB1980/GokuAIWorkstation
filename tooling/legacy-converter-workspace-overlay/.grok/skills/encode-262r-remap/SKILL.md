---
name: encode-262r-remap
description: >-
  Persist a proven NeoForge 26.2 migration fix into 262r knowledge and the
  converter so Mode B does not rediscover it. Use after a green repair when
  encoding remaps, shards, catalog entries, or Convert-Forge1201-ToNeoForge262.ps1
  passes. Slash: /encode-262r-remap.
---

# Encode 262r remap

## When

Only after the fix is proven (destination-Java build green for that family) or clearly mechanical and already matched to exact 26.2 evidence.

## Steps

1. Identify detect cue → target shape (one row).
2. Add or update **one** shard under `C:\gokuai\Data\262r\shards\` (or `converter/` for pipeline notes).
3. Add ledger row to `C:\gokuai\Data\262r\remaps.md` and/or `do-not.md` if it is an anti-pattern.
4. Update `C:\gokuai\Data\262r\catalog.json` with id + file + summary.
5. Encode the mechanical rewrite into `tools/Convert-Forge1201-ToNeoForge262.ps1` (or `ConversionCore.ps1`) when automatable.
6. Mirror into packaging `knowledge-backup/262r` when releasing.
7. Keep shard bodies short; link primer/physical evidence with paths - do not paste whole primers.
8. Refresh the link-only index used by skills:
   regenerate `.grok/skills/repair-failed-262-output/references/262r-shard-index.md` from `catalog.json` (ids/summaries only).
9. Run `tools/Lint-MigrationSkills.ps1` before calling the encode done.

## Do not

- Duplicate the same fact into AGENTS.md or skill bodies.
- Encode speculative fixes that never compiled.
