---
name: minecraft-knowledge
description: >-
  Minecraft/Forge/NeoForge API lookup, mappings, primers, Gradle/ModDevGradle,
  GeckoLib, or completed-project patterns via MCP. Use when searching APIs,
  resolving mappings, building migration evidence, or asking how a solved
  project fixed something. Slash: /minecraft-knowledge.
---

# Minecraft Knowledge Retrieval

## Do

1. Read `.grok/rules/knowledge-sources.md` for declared versions and roots.
2. Once per parent session: `minecraft-knowledge__knowledge_status` + `list_knowledge_sources` if readiness is uncertain.
3. Entrypoints: `resolve_reference(kind, version)` or `resolve_primer_chain(source, "26.2")`.
4. Before API edits on long-range migrations: `build_migration_evidence(source, "26.2", query)` (capped packet).
5. Hosted Grok: use returned `physical_path` / `source_root` with native `read_file`/`grep` — pin the exact version directory.
6. Confirm target APIs with `grep_physical_source` / `read_physical_source` on **exact 26.2** (not adjacent).
7. Mappings: `resolve_mapping` with explicit namespaces — never guess direction.
8. Prefer category `262r` version `26.2` and `search_solved_projects` before inventing.

## Do not

- Dump full primer `index.md` bodies into context; open one compact `primer_changes` shard.
- Treat empty FTS as proof an API is absent.
- Walk all of `C:\gokuai\Data` or use `goku-data.db` for repair (legacy/benchmark only).
- Hand local workers a rediscovery task — give them a bounded evidence packet instead.

## Packet cap

Parent→worker packets ≤ ~9,000 characters: ledger pointer, ≤4 short target excerpts, mappings, current errors.
