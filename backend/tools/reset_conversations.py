#!/usr/bin/env python3
"""Clear conversation history, leaving the seeded corpus intact.

Before a demo or a manual end-to-end run, the sidebar is full of whatever the last hour
of testing produced — half-finished threads, prompt-injection probes, a dozen rows called
"New conversation". None of it is customer data and none of it is worth keeping, but it
makes the interface impossible to read and it hides the thing being demonstrated.

This removes exactly two things:

* rows in ``thread`` — the conversation list;
* everything in the checkpointer database — the graph state each conversation carried,
  including any pending interrupt.

It deliberately does **not** touch the seeded corpus (customers, policies, claims, cases,
interactions, KB articles). Those are the records the assistant reads, they are identical
on every machine by construction (docs/12), and regenerating them is a different job with
a different command: ``uv run python -m app.seed --reset``.

Tickets the agent created during testing *are* removed with ``--tickets``, because a demo
that opens on yesterday's test tickets is telling the wrong story. Their audit rows go
with them: an audit row pointing at a ticket that no longer exists is worse than neither.

Usage:
    uv run python tools/reset_conversations.py [--tickets] [--yes]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
APP_DB = BACKEND / "data" / "app.db"
CHECKPOINT_DB = BACKEND / "data" / "checkpoints.db"

#: How the assistant marks a ticket it opened. The seed writes ``agent_manual`` with a
#: human handler's name in ``created_by``, so provenance is carried here and **not** by
#: ``created_by`` — which is a person either way (app/repositories/ticket.py).
ASSISTANT_VIA = "assistant"

#: Every query below is written out in full with a bound parameter rather than composed
#: from a shared subquery constant. Slightly repetitive, and it keeps the SQL literal —
#: which is the only form a reader (and a linter) can check at a glance.


#: The only tables `counts` may be asked about. A table name cannot be a bound parameter,
#: so the safety has to come from the name never being caller-supplied in the first place.
COUNTABLE = {"thread", "checkpoints", "ticket"}


def counts(connection: sqlite3.Connection, table: str) -> int:
    if table not in COUNTABLE:
        raise ValueError(f"refusing to count an unexpected table: {table!r}")
    try:
        row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
    except sqlite3.OperationalError:
        return 0
    return int(row[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickets",
        action="store_true",
        help="also delete tickets created during testing, and their audit rows",
    )
    parser.add_argument("--yes", action="store_true", help="skip the confirmation")
    args = parser.parse_args()

    if not APP_DB.exists():
        print(f"No database at {APP_DB}. Run `uv run python -m app.seed` first.", file=sys.stderr)
        return 1

    app = sqlite3.connect(APP_DB)
    threads = counts(app, "thread")
    tickets = 0
    if args.tickets:
        # Only tickets the assistant opened. The seed writes 145 of its own with
        # `created_via = 'agent_manual'`, and deleting those would quietly change the
        # corpus that every eval and every test is written against.
        row = app.execute(
            "SELECT COUNT(*) FROM ticket WHERE created_via = ?", (ASSISTANT_VIA,)
        ).fetchone()
        tickets = int(row[0])

    checkpoint_rows = 0
    if CHECKPOINT_DB.exists():
        checkpoints = sqlite3.connect(CHECKPOINT_DB)
        checkpoint_rows = counts(checkpoints, "checkpoints")
        checkpoints.close()

    plan = f"{threads} thread(s), {checkpoint_rows} checkpoint(s)"
    if args.tickets:
        plan += f", {tickets} agent-created ticket(s)"
    print(f"About to delete: {plan}")
    print("The seeded corpus (customers, policies, claims, cases, KB) is untouched.")

    if not args.yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Nothing deleted.")
            app.close()
            return 0

    with app:
        app.execute("DELETE FROM thread")
        if args.tickets:
            # Audit rows first: they reference the ticket, and an audit trail pointing at
            # a row that no longer exists is worse than having neither.
            app.execute(
                "DELETE FROM audit_log WHERE target_id IN "
                "(SELECT ticket_id FROM ticket WHERE created_via = ?)",
                (ASSISTANT_VIA,),
            )
            app.execute(
                "DELETE FROM ticket_event WHERE ticket_id IN "
                "(SELECT ticket_id FROM ticket WHERE created_via = ?)",
                (ASSISTANT_VIA,),
            )
            app.execute("DELETE FROM ticket WHERE created_via = ?", (ASSISTANT_VIA,))
    app.close()

    if CHECKPOINT_DB.exists():
        checkpoints = sqlite3.connect(CHECKPOINT_DB)
        with checkpoints:
            checkpoints.execute("DELETE FROM writes")
            checkpoints.execute("DELETE FROM checkpoints")
        checkpoints.close()

    print(f"Cleared {plan}.")
    print("Restart the backend if it is running — it holds an open connection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
