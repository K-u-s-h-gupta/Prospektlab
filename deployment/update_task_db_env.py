import json
import sys

input_path = sys.argv[1] if len(sys.argv) > 1 else "task-def.json"
output_path = sys.argv[2] if len(sys.argv) > 2 else "task-def-new.json"

with open(input_path, encoding="utf-8-sig") as f:
    payload = json.load(f)

task = payload["taskDefinition"]
env = task["containerDefinitions"][0]["environment"]
by_name = {item["name"]: item for item in env}

memory_url = by_name.get("MEMORY_DATABASE_URL", {}).get("value", "").strip()
if not memory_url:
    raise SystemExit("MEMORY_DATABASE_URL missing from task definition")

for key in ("IKG_DATABASE_URL", "DATABASE_URL", "SUPABASE_DB_URL"):
    by_name[key] = {"name": key, "value": memory_url}

task["containerDefinitions"][0]["environment"] = list(by_name.values())
for field in (
    "taskDefinitionArn",
    "revision",
    "status",
    "requiresAttributes",
    "compatibilities",
    "registeredAt",
    "registeredBy",
):
    task.pop(field, None)

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(task, f)

print(f"Wrote {output_path}")
