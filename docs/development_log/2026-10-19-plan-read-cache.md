# Reuse unchanged persisted plan state

User approved reuse of unchanged plan state after dev.311 startup measurements
showed repeated expensive commitment preparation and review reads. The diagnostic
archive from 2026-10-19 19:14 contains a 116,777,739-byte commitment state file.
Review preparation loads 42 daily assignments and then their PV comparisons,
previously decoding the entire file 43 times.

ActivePlanCommitmentStore now uses one internal read snapshot for audited
read-only methods. Device/inode, size and nanosecond modification/change times
are checked on each lookup. Parsing checks the signature again and retries a
concurrent replacement at most three times. Read failures invalidate the cache;
there is no stale fallback. Existing missing-file semantics are preserved.

Writers retain fresh private payloads and invalidate cached data before loading
and around publication. Mutable nested recalculation results are deep-copied
before returning. Legacy load() retains its existing tolerant error semantics.
No planner policy, measurement refresh, execution authority or file format changes.
This does not add transactional isolation across multiple store calls.

Local Windows replay of the 43-lookups workload produced identical result hashes:
fresh reads 43, 113.118 s; cached reads 1, 0.753 s. Integration tests were also
running, so timings are illustrative, not an isolated performance guarantee or
an HA startup prediction. Separate processes measured peak working sets of
411.0 versus 409.3 MiB. Retained working set increased from 40.4 to 299.3 MiB:
the parsed snapshot costs about 259 MiB while retained. Writes release the
store's cached reference before decoding their private payload.

Focused tests cover concurrent readers, same-size/same-mtime atomic replacement,
external edits, corruption, deletion/recreation, writer isolation, detached
returned data and replacement during parsing. The affected integration suite
passed all 143 tests in 234.85 seconds. Ruff and Linux-targeted mypy pass.
HA startup time and memory after deployment remain to be measured. Not released.
