lazy from backend_logic._shared.json.contracts import JsonValue

# An object with exactly the declared keys whose value types are not yet checked.
type NoteFields = dict[str, JsonValue]
