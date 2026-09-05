# GokuAI project policy

Parent: **Grok 4.5** (`reasoning_effort = medium`).  
Workers: local **EXL3** aliases (`goku-code`, `goku-heavy`, `goku-research`).

## Mission

Minimize parent token use. The parent plans, delegates, verifies compact summaries, and recovers. Workers own large context.

## Parent rules

1. Prefer `spawn_subagent` for research, coding, and review. Do not pull large file bodies or build logs into the parent when a path works.
2. Subagent prompts must be narrow: goal, acceptance criteria, relevant **paths**, and at most a small error excerpt.
3. Treat worker replies as summaries. Read artifact paths only when needed.
4. On worker failure / low confidence / tool errors:
   - Read the summary + small error slice only.
   - Produce a corrected brief (missing APIs, tighter scope, concrete hints).
   - Retry with a new spawn or `resume_from` the same worker.
5. Escalation budget: **2 local retries → 1 Grok rebrief → 1 more local attempt → optional parent hotfix**. Then return control to EXL3 when possible.
6. Prefer sequential local workers on this single-GPU station (backend is batch-1).

## Worker rules

1. One scoped task per spawn.
2. Write bulky output under `.gokuai/tasks/<task-id>/`.
3. Return the compact contract (status, files, evidence paths, validation, unresolved, confidence, next step).
4. Do not ask the parent to paste entire files; read them yourself.

## Backend notes (Mia Qwen3.8-27B EXL3)

- Always-on reasoning may consume part of `max_tokens`; keep completion budgets generous.
- Tool calls must be structured OpenAI `tool_calls`.
- Discover the live model id from `/v1/models` if aliases fail.
