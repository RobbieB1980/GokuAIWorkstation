# Parent → worker spawn packet contract

Use with `spawn_subagent` `subagent_type`: `mc-research` | `mc-fast` | `mc-code` | `mc-reviewer`.

## Required fields in the prompt

1. **FAILED OUTPUT / project root** (absolute path)
2. **Evidence packet path** (`EVIDENCE_PACKET.md`) — must exist before `mc-code` / `mc-fast` / `mc-reviewer`
3. **Error family** (one line)
4. **Acceptance** (usually destination-Java build → jar)
5. **Validation command** (Build-WithDestinationJava.ps1)
6. For implementers: **explicit file list** when known
7. For reviewers: **changed files + build log path**

## Forbidden in worker prompts

- Full primer `index.md` bodies
- Entire `compile-errors.log` (trim to the family)
- “Search all of Data and figure it out”
- Multiple unrelated error families in one spawn

## Sequence (single GPU)

```text
parent fills packet
  → mc-research (optional, if evidence thin)
  → mc-fast OR mc-code
  → parent validate-destination-build
  → mc-reviewer (optional / high risk)
  → encode-262r-remap (if reusable)
```

One local/heavy worker at a time. Prefer sequential spawns over parallel on one CUDA backend.
