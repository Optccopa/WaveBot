# Project Rules

### WORKFLOW - FOLLOW EVERY CODE CHANGE
1. Check docs/ for relevant context before writing anything
2. Make the code change
3. Update docs/ to reflect the change before considering the task done
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