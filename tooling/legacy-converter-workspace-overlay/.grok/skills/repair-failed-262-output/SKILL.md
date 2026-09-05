---
name: repair-failed-262-output
description: >-
  Repair a failed RB Legacy Java Converter NeoForge 26.2 output folder.
  Use for Fix-in-Grok, GROK_REPAIR_PROMPT.md, compile-errors.log repair,
  or any failed-output path that needs green gradlew build. Slash: /repair-failed-262-output.
---

# Repair failed 26.2 output

## First actions

1. Read `GROK_REPAIR_PROMPT.md` (names **FAILED OUTPUT FOLDER**).
2. Read `MIGRATION_EVIDENCE.md`, `SOURCE_PROFILE.json`, `compile-errors.log`.
3. Copy/fill an evidence packet beside the failed output:
   - Template: `references/evidence-packet-template.md`
   - Suggested path: `<FAILED OUTPUT>\EVIDENCE_PACKET.md` (keep under ~9k chars)
4. State detected `source_version` + primer ledger path before editing.

## Knowledge order (one file at a time)

1. `C:\gokuai\Data\262r\converter\` then matching `shards\` (one shard)
2. Solved cases under `C:\gokuai\Data\Solved_Problems\legacy-java-converter-26.2`
3. One `primer_changes` shard for detected-source → 26.2
4. Exact 26.2 physical source confirmation
5. Edit → validate → encode

## Validation

Use skill `validate-destination-build` (JDK 25).  
`Gradle requires JVM 17+ ... JVM 8` = wrong JDK, not a mod bug.

## Session hygiene

After a green jar **or** a finished error family, prefer a **fresh chat** with only: failed-output path + `EVIDENCE_PACKET.md` + next error family. Do not carry a huge tool transcript into unrelated remaps.

## Agents

After the packet exists:

1. Optional `mc-research` if the matching 262r shard is unclear
2. `mc-fast` or `mc-code` with the packet path in the prompt
3. Parent `/validate-destination-build`
4. Optional `mc-reviewer`
5. `/encode-262r-remap` when reusable

See `../migrate-neoforge-262/references/spawn-packet-contract.md`.  
Shard id cheat-sheet (links only): `references/262r-shard-index.md`.

## Encode

Reusable fixes → skill `encode-262r-remap`.
