---
description: Update docs/20-implementation-status.md and verify it against the tree
---

# Checkpoint the implementation status

`docs/20-implementation-status.md` is the answer to "what is actually built here?"
Everything else in `docs/` reads identically whether or not code exists behind it, which
is exactly why that document has to stay current.

Do this **as part of any change that adds, removes, or completes a component** — not as a
separate follow-up:

1. Read `docs/20-implementation-status.md`.
2. Update the rows this change moved. Use the vocabulary strictly (§3):
   - **Built** — implemented *and* covered by a suite named in §5. Code with no test that
     would fail if it broke is **Partial**, whatever the effort spent.
   - **Partial** — implemented, with the limitation stated in the row.
   - **Specified** — a document describes it, no code exists.
   - **Declined** — deliberately not done, with the reason and where it is argued.
3. If the change moved a row out of **Specified**, say in §5 which suite now covers it.
   A row promoted to **Built** without a test named is the failure this document exists
   to prevent.
4. Refresh the counts and the verification date:
   ```bash
   python3 tools/check_implementation_status.py --update-counts
   ```
5. Verify:
   ```bash
   python3 tools/check_implementation_status.py
   ```

If the checker fails, **fix the rows, not the checker** — unless the checker itself is
wrong, in which case fix it and say so in the commit.

Also update §6 (Gaps) when this change closes one or opens one.
