"""Dump the durable rows behind each acceptance task: attempts, effects, turns, audit.

Reads through the system role (row-level security applies to the app role).
Prints counts and duplicates only; no prompts, paths or secrets.
"""
import asyncio, json, os, sys
import asyncpg

TASKS = sys.argv[1:]

async def main():
    conn = await asyncpg.connect(os.environ["ACCEPTANCE_SYSTEM_DSN"])
    out = {}
    for t in TASKS:
        atts = await conn.fetch(
            "select id, attempt_number, status, completion_reason, error_code, recoveries, "
            "session_id, worktree_id, chat_turn_id from task_attempts where task_id=$1 order by attempt_number", t)
        effects = await conn.fetch(
            "select kind, effect_key, status from work_effects where task_id=$1 order by created_at", t)
        turn_ids = [a["chat_turn_id"] for a in atts if a["chat_turn_id"]]
        turns = await conn.fetch(
            "select id, status, execution_id from chat_turns where id = any($1::uuid[])", turn_ids)
        audit = await conn.fetch(
            "select action, count(*) n from audit_log where resource_id = any($1::text[]) "
            "group by action order by action", [str(a["id"]) for a in atts] + [t])
        keys = [e["effect_key"] for e in effects]
        out[t] = {
            "attempts": [{k: (str(v) if v is not None else None) for k, v in dict(a).items()} for a in atts],
            "work_effects": [dict(e) for e in effects],
            "duplicate_effect_keys": sorted({k for k in keys if keys.count(k) > 1}),
            "chat_turns": [{k: str(v) for k, v in dict(r).items()} for r in turns],
            "audit_actions": {r["action"]: r["n"] for r in audit},
        }
    print(json.dumps(out, indent=1))
    await conn.close()

asyncio.run(main())
