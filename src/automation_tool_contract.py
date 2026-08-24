"""Canonical agent schemas for validated structured automations."""

def tool(name, description, actions, destructive=False):
    return {"type":"function","function":{"name":name,"description":description,"parameters":{"type":"object","properties":{"action":{"type":"string","enum":sorted(actions)},"automation_id":{"type":"string"},"run_id":{"type":"string"},"step_index":{"type":"integer","minimum":0,"maximum":24},"definition":{"type":"object","additionalProperties":True},"status":{"type":"string","enum":["enabled","paused"]},"inputs":{"type":"object","additionalProperties":True},"dedupe_key":{"type":"string","maxLength":300},"version":{"type":"integer","minimum":1},"limit":{"type":"integer","minimum":1,"maximum":500}},"required":["action"]+(["version"] if destructive else []),"additionalProperties":False}}}
QUERY_AUTOMATIONS_TOOL_SCHEMA=tool("query_automations","Read structured automation definitions and full run history without changing them.",{"list","get","list_runs"})
MANAGE_AUTOMATION_TOOL_SCHEMA=tool("manage_automation","Create, pause, enable, manually run, or approve one exact paused step in a validated bounded automation.",{"approve_step","create","set_status","run"})
DELETE_AUTOMATION_TOOL_SCHEMA=tool("delete_automation","Delete one exact automation after destructive approval and version checking.",{"delete"},True)
AUTOMATION_TOOL_SCHEMAS=(QUERY_AUTOMATIONS_TOOL_SCHEMA,MANAGE_AUTOMATION_TOOL_SCHEMA,DELETE_AUTOMATION_TOOL_SCHEMA)
