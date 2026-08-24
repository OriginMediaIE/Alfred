"""Canonical schemas for user-approved personal-life records."""
QUERY_LIFE_ACTIONS=frozenset({"list","get"});MANAGE_LIFE_ACTIONS=frozenset({"create","update"});DELETE_LIFE_ACTIONS=frozenset({"delete"})
def _schema(name,description,actions):
    return {"type":"function","function":{"name":name,"description":description,"parameters":{"type":"object","properties":{"action":{"type":"string","enum":sorted(actions)},"kind":{"type":"string","enum":["relationship","admin","trip","travel_item"]},"record_id":{"type":"string"},"trip_id":{"type":"string"},"status":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":500},"record":{"type":"object","additionalProperties":True},"revision":{"type":"integer","minimum":1}},"required":["action","kind"],"additionalProperties":False}}}
QUERY_LIFE_TOOL_SCHEMA=_schema("query_life","Read owner-scoped, user-approved relationship profiles, personal administration records, trips, and travel items.",QUERY_LIFE_ACTIONS)
MANAGE_LIFE_TOOL_SCHEMA=_schema("manage_life","Create or revise user-approved relationship, opt-in administration, and non-booking travel records after approval.",MANAGE_LIFE_ACTIONS)
DELETE_LIFE_TOOL_SCHEMA=_schema("delete_life","Permanently delete one exact personal-life record after explicit destructive approval and revision checking.",DELETE_LIFE_ACTIONS)
LIFE_TOOL_SCHEMAS=(QUERY_LIFE_TOOL_SCHEMA,MANAGE_LIFE_TOOL_SCHEMA,DELETE_LIFE_TOOL_SCHEMA)
