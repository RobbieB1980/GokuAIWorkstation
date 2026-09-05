# Knowledge index policy (GokuAI only)

Canonical Minecraft knowledge index:

- Root: `C:\gokuai\Data` (`source_id=local`)
- DB: `C:\gokuai\DataIndex\minecraft-knowledge\` (see `_ACTIVE_DB.txt`)
- Manifest: `C:\gokuai\Data\external_sources.json` must have `"sources": []`

**Do not** register `H:\GrokBuild_MF\Completed_Projects` or other external trees.

Rebuild:

```powershell
C:\gokuai\runtime\.venv\Scripts\python.exe C:\gokuai\scripts\index_knowledge.py `
  --root C:\gokuai\Data `
  --db C:\gokuai\DataIndex\minecraft-knowledge\knowledge.db `
  --sources-manifest C:\gokuai\Data\external_sources.json
```

Refresh project rules:

```powershell
C:\gokuai\runtime\.venv\Scripts\python.exe C:\gokuai\scripts\generate_project_knowledge_context.py `
  --root C:\gokuai --project C:\gokuai\projects\RB-Legacy-Java-Converter
```
