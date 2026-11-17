"""The stored note record's shared operations; the record itself (NoteRecord) is save's.

A grouping has no run: callers call the operation they need (decode) directly. save reads
the predecessor it replaces, summarize the note it hands to an agent; both admit the stored
document through the same decoder, so a record one accepts the other cannot refuse.
"""
