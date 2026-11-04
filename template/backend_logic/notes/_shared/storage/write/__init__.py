"""Publish one JSON document atomically, with an explicit durability receipt.

Never acquires locks: the caller holds its named lock across read/modify/write.
No multi-file transaction, automatic retry or rollback after publication.
"""
