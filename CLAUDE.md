# Project Rules

### Docs
- Anytime you update code you must also update docs/ and audit files in audits/ with any updated info, use the same format already present.
- Always check docs/ for information before writing code or fixing issues.
### Caching
- Cache expensive computations and frequent reads in Redis.
### Basic Security
- Every public command must have a cooldown rate of 1 use / 10 seconds.
### Persistance
- Persist any values that aren't derived or computed at runtime to postgres.
### Coding Guidelines
- Prioritize runtime speed over code elegance, but not at the cost of changing unrelated code.
- Only abstract functions that are used in multiple places and very long.
- Ignore tests/ the files are temp testing files that are kept around.
- Fixes should be surgical, avoid changing any surrounding code.
- If anything in src/prompts.py is updated you must also update the claude cache version in config.yaml.
### The Council
- If the user asks for code reviews reffer to COUNCIL.md for subagent review guidelines