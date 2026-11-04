lazy from backend_logic.json.validate.contracts import JsonValue

# The published schema-1 form: every NoteRecord field, timestamps as ISO text.
type NoteDocument = dict[str, JsonValue]
