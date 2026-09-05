"""Continuum - a memory-powered accountability runtime for autonomous agents.

Continuum turns vendor commitments into durable, structured memory in Sibyl,
then drives a *resumable* accountability workflow off that memory:

    detect breach -> decide consequence -> attest on-chain (Base) -> close

Sibyl does the load-bearing work across three memory tiers (see ``SibylMemory``):

  * WARM  entity   ``ticket/<id>``       per-commitment operational state + saga cursor
  * WARM  entity   ``vendor/<id>``       institutional vendor reputation (derived)
  * HOT   state    ``agent_reputation``  compounding agent-level reputation
  * COLD  journal  ``write_event(...)``  append-only evaluated/acted/forward ledger

Reputation is DERIVED from durable ticket history (never blindly incremented, so
reprocessing a breach can't double-count it) and fed FORWARD into the consequence
policy: a repeat-offending vendor is escalated harder for the same lateness.

The only external side effect on the core path is the Base Sepolia attestation.
It broadcasts a real transaction, so it is an EXPLICIT, opt-in step
(``allow_attestation`` / the ``attest`` command) - never a side effect of routine
breach detection or a deadline sweep.

Virtuals ACP is deliberately NOT on the core path. The runtime is fully functional
with Sibyl + Base alone. ``VirtualsCoordinator`` remains as a clean, unwired
integration seam - a real client, never a fake - for when ACP credentials exist.

Remove Sibyl and there is no state, no recall, and no consequence - memory is the
product. There is deliberately no JSON / local-development substitute.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass


# --------------------------------------------------------------------------- #
# Configuration & time
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SIBYL_DB = Path(os.getenv("SIBYL_MEMORY_DB", str(DATA / "sibyl_memory.db"))).resolve()
SIBYL_TENANT = os.getenv("SIBYL_TENANT_ID", "00000000-0000-0000-0000-000000000001")
BASE_SEPOLIA_CHAIN_ID = 84532


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("promised_date must include a timezone")
    return parsed


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Ticket schema - a ticket is one commitment; ``phase`` is the saga cursor
# --------------------------------------------------------------------------- #
PHASES = ("OPEN", "BREACHED", "ATTESTED", "CLOSED")
STATUSES = ("pending", "broken", "resolved")

REQUIRED_FIELDS = {
    "ticket_id", "customer_id", "vendor_id", "issue_summary",
    "promise_made", "promised_date", "status", "phase",
    "escalation_count", "escalation_level", "resolution_credit",
    "vendor_tier_at_breach", "breach_event_id",
    "attestation_intent", "attestation_tx_hash", "attestation_timestamp",
    "resolved_at", "last_action",
}


def new_ticket(ticket_id, customer_id, vendor_id, issue_summary, promise_made, promised_date):
    """Create a fresh OPEN commitment, validated before it is ever stored."""
    return validate({
        "ticket_id": ticket_id,
        "customer_id": customer_id,
        "vendor_id": vendor_id,
        "issue_summary": issue_summary,
        "promise_made": promise_made,
        "promised_date": promised_date,
        "status": "pending",
        "phase": "OPEN",
        "escalation_count": 0,
        "escalation_level": 0,
        "resolution_credit": 0,
        "vendor_tier_at_breach": None,
        "breach_event_id": None,
        "attestation_intent": None,
        "attestation_tx_hash": None,
        "attestation_timestamp": None,
        "resolved_at": None,
        "last_action": "promise recorded",
    })


def validate(ticket):
    missing = REQUIRED_FIELDS - set(ticket)
    if missing:
        raise ValueError("ticket missing required fields: " + ", ".join(sorted(missing)))
    if ticket["status"] not in STATUSES:
        raise ValueError(f"invalid status: {ticket['status']!r}")
    if ticket["phase"] not in PHASES:
        raise ValueError(f"invalid phase: {ticket['phase']!r}")
    parse_date(ticket["promised_date"])  # raises on bad format / naive datetime
    return ticket


# --------------------------------------------------------------------------- #
# Policy - deterministic AND reputation-aware (institutional memory feeds forward)
# --------------------------------------------------------------------------- #
def base_credit(days_late: int) -> int:
    """Baseline customer credit owed, by how many days the promise slipped."""
    if days_late <= 0:
        return 0
    if days_late == 1:
        return 5
    if days_late <= 3:
        return 10
    return 20


def base_escalation_level(days_late: int) -> int:
    if days_late <= 0:
        return 0
    if days_late <= 1:
        return 1
    if days_late <= 3:
        return 2
    return 3


def reliability_tier(reliability: float) -> str:
    if reliability >= 0.9:
        return "trusted"
    if reliability >= 0.6:
        return "standard"
    if reliability >= 0.3:
        return "watch"
    return "high-risk"


_REPEAT_CREDIT_FACTOR = {"trusted": 1.0, "standard": 1.0, "watch": 1.5, "high-risk": 2.0}
_TIER_ESCALATION_BUMP = {"trusted": 0, "standard": 0, "watch": 1, "high-risk": 2}


def consequence(days_late: int, prior_tier: str) -> dict:
    """The forward-looking decision.

    Identical lateness costs a repeat offender more, because the vendor's prior
    reliability (recalled from memory) raises both the escalation level and the
    credit multiplier. This is where institutional memory changes the action.
    """
    return {
        "escalation_level": base_escalation_level(days_late) + _TIER_ESCALATION_BUMP[prior_tier],
        "resolution_credit": round(base_credit(days_late) * _REPEAT_CREDIT_FACTOR[prior_tier]),
    }


def derive_vendor_reputation(vendor_id, tickets, exclude_ticket_id=None):
    """Institutional vendor reputation, computed purely from durable ticket history.

    Deriving (rather than incrementing a counter) makes reputation idempotent by
    construction: reprocessing the same breach cannot double-count it. Pass
    ``exclude_ticket_id`` to get the vendor's *prior* standing, before the ticket
    currently being judged is folded in.
    """
    rows = [t for t in tickets
            if t["vendor_id"] == vendor_id and t["ticket_id"] != exclude_ticket_id]
    commitments = len(rows)
    breaches = sum(1 for t in rows if t.get("breach_event_id"))
    on_time = sum(1 for t in rows if t["status"] == "resolved" and not t.get("breach_event_id"))
    credit_charged = sum(t.get("resolution_credit", 0) for t in rows if t.get("breach_event_id"))
    last_breach_at = max((t["breach_event_id"] for t in rows if t.get("breach_event_id")), default=None)
    reliability = 1.0 - (breaches / commitments) if commitments else 1.0
    return {
        "vendor_id": vendor_id,
        "commitments": commitments,
        "breaches": breaches,
        "on_time_resolutions": on_time,
        "breach_rate": round(breaches / commitments, 4) if commitments else 0.0,
        "reliability": round(reliability, 4),
        "tier": reliability_tier(reliability),
        "total_credit_charged": credit_charged,
        "last_breach_at": last_breach_at,
        "updated_at": iso(now()),
    }


def derive_agent_reputation(tickets):
    """Compounding agent-level reputation, computed from durable ticket history."""
    breached = [t for t in tickets if t.get("breach_event_id")]
    return {
        "agent_id": "continuum-support-01",
        "tickets_processed": len(tickets),
        "promises_tracked": len(tickets),
        "breaches_detected": len(breached),
        "escalations_issued": sum(t.get("escalation_count", 0) for t in tickets),
        "credit_recovered": sum(t.get("resolution_credit", 0) for t in breached),
        "attestations_created": sum(1 for t in tickets if t.get("attestation_tx_hash")),
        "updated_at": iso(now()),
    }


# --------------------------------------------------------------------------- #
# Memory - Sibyl is the ONLY production store (no JSON / local substitute)
# --------------------------------------------------------------------------- #
class SibylMemory:
    """Load-bearing memory over the Sibyl SDK.

    Tickets and vendor reputation are WARM entities, agent reputation is a HOT
    state document, and every consequential transition is appended to the COLD
    journal as an ``evaluated`` / ``acted`` / ``forward`` event.
    """

    backend_name = "sibyl-sdk-sqlite"

    def __init__(self, db=SIBYL_DB, tenant=SIBYL_TENANT):
        try:
            from sibyl_memory_client import MemoryClient
        except ImportError as exc:
            raise RuntimeError("Install sibyl-memory-client before running Continuum") from exc
        self.client = MemoryClient.local(str(db), tenant_id=tenant)

    # -- tickets ----------------------------------------------------------- #
    def get(self, ticket_id):
        from sibyl_memory_client.exceptions import NotFoundError

        try:
            return validate(self.client.get_entity("ticket", ticket_id)["body"])
        except NotFoundError:
            return None

    def put(self, ticket):
        validate(ticket)
        previous = self.get(ticket["ticket_id"])
        if previous and previous["status"] == "broken" and ticket["status"] == "pending":
            raise ValueError("a broken ticket cannot regress to pending")
        self.client.set_entity("ticket", ticket["ticket_id"], ticket, status=ticket["status"])

    def all(self):
        return [validate(row["body"]) for row in self.client.list_entities("ticket", limit=10000)]

    # -- reputation (derived from history, then materialized for querying) - #
    def vendor_reputation(self, vendor_id, exclude_ticket_id=None):
        return derive_vendor_reputation(vendor_id, self.all(), exclude_ticket_id)

    def agent_reputation(self):
        return derive_agent_reputation(self.all())

    def refresh_reputation(self, vendor_id):
        vendor = self.vendor_reputation(vendor_id)
        self.client.set_entity("vendor", vendor_id, vendor, status=vendor["tier"])
        self.client.set_state("agent_reputation", self.agent_reputation())
        return vendor

    # -- append-only consequence ledger ------------------------------------ #
    def append_ledger(self, ticket_id, kind, evaluated, acted, forward):
        self.client.write_event(
            evaluated=evaluated, acted=acted, forward=forward,
            extra={"ticket_id": ticket_id, "kind": kind},
        )

    def ledger(self, limit=50):
        return self.client.read_events(limit=limit)

    def clear(self):
        for category in ("ticket", "vendor"):
            for row in self.client.list_entities(category, limit=10000):
                self.client.delete_entity(category, row["name"])


class InMemoryStore:
    """Test-only backend mirroring ``SibylMemory``'s interface with plain dicts.

    It lets the workflow, policy, and reputation logic be unit-tested without a
    Sibyl install. It is never used in production.
    """

    backend_name = "in-memory-test"

    def __init__(self):
        self.rows = {}
        self.vendors = {}
        self.agent = {}
        self.events = []

    def _copy(self, value):
        return json.loads(json.dumps(value))

    def get(self, ticket_id):
        row = self.rows.get(ticket_id)
        return self._copy(row) if row else None

    def put(self, ticket):
        validate(ticket)
        previous = self.rows.get(ticket["ticket_id"])
        if previous and previous["status"] == "broken" and ticket["status"] == "pending":
            raise ValueError("a broken ticket cannot regress to pending")
        self.rows[ticket["ticket_id"]] = self._copy(ticket)

    def all(self):
        return [self._copy(row) for row in self.rows.values()]

    def vendor_reputation(self, vendor_id, exclude_ticket_id=None):
        return derive_vendor_reputation(vendor_id, self.all(), exclude_ticket_id)

    def agent_reputation(self):
        return derive_agent_reputation(self.all())

    def refresh_reputation(self, vendor_id):
        vendor = self.vendor_reputation(vendor_id)
        self.vendors[vendor_id] = vendor
        self.agent = self.agent_reputation()
        return vendor

    def append_ledger(self, ticket_id, kind, evaluated, acted, forward):
        self.events.append({
            "ticket_id": ticket_id, "kind": kind,
            "evaluated": evaluated, "acted": acted, "forward": forward,
        })

    def ledger(self, limit=50):
        return list(reversed(self.events))[:limit]

    def clear(self):
        self.rows.clear()
        self.vendors.clear()
        self.agent = {}
        self.events.clear()


# --------------------------------------------------------------------------- #
# External effects - Base attestation (real, on the core path)
# --------------------------------------------------------------------------- #
class PartnerNotConfigured(RuntimeError):
    """A partner's credentials are absent.

    Expected off-production. The ticket stays durably at its current phase and
    the workflow resumes from exactly there once the partner is configured.
    """


class PartnerError(RuntimeError):
    """A configured partner call failed (bad response, wrong chain, etc.)."""


class BaseAttestor:
    """Writes a tamper-evident breach attestation to Base Sepolia.

    The signed-transaction intent (nonce + payload hash) is persisted BEFORE
    broadcast, so a crash-retry re-sends the identical transaction on the same
    nonce instead of double-spending. This is the only external side effect on
    the core path, and the runtime only ever calls it under an explicit opt-in.
    """

    def payload(self, ticket):
        return {
            "vendor_id_hash": digest(ticket["vendor_id"]),
            "ticket_id_hash": digest(ticket["ticket_id"]),
            "commitment_hash": digest(ticket["promise_made"]),
            "promised_date": ticket["promised_date"],
            "breached_at": ticket["breach_event_id"],
        }

    def submit(self, ticket, store):
        if not os.getenv("BASE_PRIVATE_KEY") or not os.getenv("BASE_RPC_URL"):
            raise PartnerNotConfigured("Base credentials are required; no local substitute exists")
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(os.environ["BASE_RPC_URL"]))
        if w3.eth.chain_id != BASE_SEPOLIA_CHAIN_ID:
            raise PartnerError(f"Base Sepolia ({BASE_SEPOLIA_CHAIN_ID}) is required")
        account = w3.eth.account.from_key(os.environ["BASE_PRIVATE_KEY"])
        payload = self.payload(ticket)
        intent = ticket.get("attestation_intent")
        nonce = intent["nonce"] if intent else w3.eth.get_transaction_count(account.address, "pending")
        tx = {
            "from": account.address, "to": account.address, "value": 0,
            "data": w3.to_hex(text=json.dumps(payload, separators=(",", ":"))),
            "nonce": nonce, "chainId": BASE_SEPOLIA_CHAIN_ID, "gas": 100000,
            "maxFeePerGas": w3.to_wei(1, "gwei"), "maxPriorityFeePerGas": w3.to_wei(1, "gwei"),
        }
        signed = account.sign_transaction(tx)
        tx_hash = w3.to_hex(signed.hash)
        if not intent:  # persist intent before broadcast -> nonce-stable replay
            ticket["attestation_intent"] = {
                "tx_hash": tx_hash, "nonce": nonce,
                "payload_hash": digest(json.dumps(payload, sort_keys=True)),
            }
            store.put(ticket)
        w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(tx_hash)
        return tx_hash, iso(now())


# --------------------------------------------------------------------------- #
# Workflow - a resumable saga
#
# Phases: OPEN -> BREACHED -> ATTESTED -> CLOSED. Each arrow is guarded ONLY by
# durable state (``phase`` + the presence of a result like ``attestation_tx_hash``),
# so a crash at any arrow resumes from exactly that arrow and never double-acts.
#
# Breach detection (OPEN -> BREACHED) is pure memory work and always runs. The
# ATTESTED arrow broadcasts a real Base transaction, so it fires ONLY when the
# caller opts in via ``allow_attestation``; otherwise the saga reaches a safe
# fixpoint at BREACHED and resumes later. This keeps routine processing and the
# deadline sweep from ever spending on-chain by accident.
# --------------------------------------------------------------------------- #
class AccountabilityRuntime:
    def __init__(self, memory, attestor=None, clock=now, allow_attestation=False):
        self.memory = memory
        self.attestor = attestor or BaseAttestor()
        self.clock = clock
        self.allow_attestation = allow_attestation

    def process(self, ticket_id):
        """Drive a ticket to a fixpoint: keep advancing until no arrow fires."""
        ticket = self.memory.get(ticket_id)
        if ticket is None:
            return None
        while True:
            phase = ticket["phase"]
            ticket = self._advance(ticket)
            if ticket["phase"] == phase:
                return ticket

    def _advance(self, ticket):
        transitions = {
            "OPEN": self._open_to_breached,
            "BREACHED": self._breached_to_attested,
            "ATTESTED": self._attested_to_closed,
        }
        return transitions.get(ticket["phase"], lambda t: t)(ticket)

    def _open_to_breached(self, ticket):
        due = parse_date(ticket["promised_date"])
        days_late = (self.clock() - due).total_seconds() / 86400
        if days_late <= 0:
            return ticket  # not yet due - stays OPEN, no consequence

        prior = self.memory.vendor_reputation(ticket["vendor_id"], exclude_ticket_id=ticket["ticket_id"])
        decided = consequence(max(1, int(days_late)), prior["tier"])
        ticket.update(
            status="broken",
            phase="BREACHED",
            breach_event_id=iso(self.clock()),
            escalation_count=ticket["escalation_count"] + 1,
            escalation_level=decided["escalation_level"],
            resolution_credit=decided["resolution_credit"],
            vendor_tier_at_breach=prior["tier"],
            last_action="deadline breach detected",
        )
        self.memory.put(ticket)
        after = self.memory.refresh_reputation(ticket["vendor_id"])
        self.memory.append_ledger(
            ticket["ticket_id"], "breach",
            evaluated={
                "promised_date": ticket["promised_date"],
                "observed_at": ticket["breach_event_id"],
                "days_late": int(days_late),
                "prior_breaches": prior["breaches"],
                "prior_tier": prior["tier"],
            },
            acted={
                "transition": "OPEN->BREACHED",
                "escalation_level": decided["escalation_level"],
                "resolution_credit": decided["resolution_credit"],
            },
            forward={
                "vendor_reliability": after["reliability"],
                "vendor_tier": after["tier"],
                "rule": "repeat offenders escalate faster and cost more",
            },
        )
        return ticket

    def _breached_to_attested(self, ticket):
        # The on-chain broadcast is the one irreversible side effect, so it fires
        # only on an explicit opt-in. Without it the saga rests safely at BREACHED.
        if not self.allow_attestation:
            return ticket
        if not ticket.get("attestation_tx_hash"):
            tx_hash, ts = self.attestor.submit(ticket, self.memory)
            ticket.update(attestation_tx_hash=tx_hash, attestation_timestamp=ts)
        ticket.update(phase="ATTESTED", last_action="base attestation confirmed")
        self.memory.put(ticket)
        self.memory.append_ledger(
            ticket["ticket_id"], "attest",
            evaluated={
                "breach_event_id": ticket["breach_event_id"],
                "escalation_level": ticket["escalation_level"],
                "resolution_credit": ticket["resolution_credit"],
            },
            acted={"transition": "BREACHED->ATTESTED", "attestation_tx_hash": ticket["attestation_tx_hash"]},
            forward={"anchored_on": "base-sepolia", "next": "close accountability cycle"},
        )
        return ticket

    def _attested_to_closed(self, ticket):
        ticket.update(phase="CLOSED", last_action="accountability cycle closed")
        self.memory.put(ticket)
        final = self.memory.refresh_reputation(ticket["vendor_id"])
        self.memory.append_ledger(
            ticket["ticket_id"], "close",
            evaluated={"attestation_tx_hash": ticket["attestation_tx_hash"]},
            acted={"transition": "ATTESTED->CLOSED"},
            forward={"vendor_reliability": final["reliability"], "vendor_tier": final["tier"]},
        )
        return ticket


def resolve_ticket(memory, ticket_id, clock=now):
    """Record that a vendor delivered.

    A pre-deadline resolution counts as on-time (good for reputation); resolving
    after a breach records the delivery but does not erase the breach.
    """
    ticket = memory.get(ticket_id)
    if ticket is None:
        return None
    ticket.update(status="resolved", resolved_at=iso(clock()), last_action="resolution recorded")
    if ticket["phase"] == "OPEN":
        ticket["phase"] = "CLOSED"
    memory.put(ticket)
    memory.refresh_reputation(ticket["vendor_id"])
    return ticket


# --------------------------------------------------------------------------- #
# Optional integrations - NOT on the core path
#
# Continuum is fully functional with Sibyl + Base alone. The class below is a
# clean, real integration seam for Virtuals ACP, kept so coordination can be
# added later without reshaping the core. It is deliberately NOT wired into
# ``AccountabilityRuntime`` and is never faked or stubbed.
#
# To enable it later: (1) restore a ``virtuals_event_id`` field on the ticket
# schema, (2) add a non-blocking BREACHED-branch that records the event id, and
# (3) supply VIRTUALS_ACP_URL / VIRTUALS_API_KEY. Until real ACP credentials
# exist, the honest state is simply "not integrated".
# --------------------------------------------------------------------------- #
class VirtualsCoordinator:
    """Coordinates a breach consequence through a Virtuals ACP workflow.

    ``breach_event_id`` is passed as the idempotency key so a retry can never
    double-fire the downstream consequence on the Virtuals side. This is a real
    client against a real endpoint; there is intentionally no local substitute.
    """

    def coordinate(self, ticket):
        url, key = os.getenv("VIRTUALS_ACP_URL"), os.getenv("VIRTUALS_API_KEY")
        if not url or not key:
            raise PartnerNotConfigured("Virtuals ACP credentials are required; no local substitute exists")
        import requests

        response = requests.post(
            url,
            json={
                "workflow": "continuum-accountability-v1",
                "idempotency_key": ticket["breach_event_id"],
                "ticket": {
                    "ticket_id_hash": digest(ticket["ticket_id"]),
                    "vendor_id_hash": digest(ticket["vendor_id"]),
                    "escalation_level": ticket["escalation_level"],
                    "credit": ticket["resolution_credit"],
                },
            },
            headers={"Authorization": "Bearer " + key},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        event_id = body.get("event_id") if isinstance(body, dict) else None
        if not isinstance(event_id, str) or not event_id:
            raise PartnerError("Virtuals response lacks event_id")
        return event_id


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
DEMO_TICKET = (
    "T-1042", "C-001", "V-001",
    "Package has not arrived.", "Resolve delivery issue",
    "2026-08-18T17:00:00+00:00",
)


def _run(memory, ticket_id, allow_attestation=False):
    """Drive one ticket through the saga and print the outcome.

    With ``allow_attestation`` false (the default for session2/session3) the run
    detects and durably records the breach but never broadcasts; it reports the
    persisted state and how to attest. If Base is simply unconfigured during an
    attest, the breach still stands and a later run resumes from exactly there.
    """
    try:
        ticket = AccountabilityRuntime(memory, allow_attestation=allow_attestation).process(ticket_id)
    except PartnerNotConfigured as exc:
        print(json.dumps({"ticket": memory.get(ticket_id), "pending": str(exc)}, indent=2, default=str))
        return
    if ticket is None:
        print(f"No Sibyl memory found for {ticket_id}")
        return
    print(json.dumps(ticket, indent=2, default=str))
    if ticket["phase"] == "BREACHED" and not allow_attestation:
        print(
            f"\nBreach recorded in Sibyl. On-chain attestation is an explicit step:\n"
            f"  python continuum.py attest {ticket_id}   # broadcasts a real Base Sepolia transaction"
        )


def main():
    parser = argparse.ArgumentParser(description="Continuum accountability runtime")
    parser.add_argument("command", choices=[
        "session1", "session2", "session3", "attest", "create-ticket", "resolve-ticket",
        "check-deadlines", "vendor", "ledger", "clear-memory", "doctor",
    ])
    parser.add_argument("target", nargs="?", default="T-1042",
                        help="ticket_id (or vendor_id for the 'vendor' command)")
    parser.add_argument("--customer-id", default="C-001")
    parser.add_argument("--vendor-id", default="V-001")
    parser.add_argument("--issue-summary", default="Support issue")
    parser.add_argument("--promise-made", default="Resolve the issue")
    parser.add_argument("--promised-date")
    args = parser.parse_args()

    memory = SibylMemory()

    if args.command == "doctor":
        print(json.dumps({
            "memory_backend": memory.backend_name,
            "sibyl_db": str(SIBYL_DB),
            "sibyl_tenant": SIBYL_TENANT,
            "tickets": len(memory.all()),
            "base_configured": bool(os.getenv("BASE_PRIVATE_KEY") and os.getenv("BASE_RPC_URL")),
            "attestation": "explicit opt-in (run: attest <ticket_id>)",
            "optional_integrations": {
                "virtuals_acp": bool(os.getenv("VIRTUALS_API_KEY") and os.getenv("VIRTUALS_ACP_URL")),
            },
        }, indent=2))
    elif args.command == "clear-memory":
        memory.clear()
        print("Sibyl Memory cleared (tickets + vendor reputation).")
    elif args.command == "session1":
        memory.put(new_ticket(*DEMO_TICKET))
        print(f"Wrote commitment {DEMO_TICKET[0]} to Sibyl (phase=OPEN).")
    elif args.command == "create-ticket":
        if not args.promised_date:
            parser.error("create-ticket requires --promised-date")
        memory.put(new_ticket(args.target, args.customer_id, args.vendor_id,
                              args.issue_summary, args.promise_made, args.promised_date))
        print(f"Wrote commitment {args.target} to Sibyl (phase=OPEN).")
    elif args.command == "resolve-ticket":
        ticket = resolve_ticket(memory, args.target)
        print(json.dumps(ticket, indent=2, default=str) if ticket else f"No Sibyl memory found for {args.target}")
    elif args.command == "vendor":
        print(json.dumps(memory.vendor_reputation(args.target), indent=2, default=str))
    elif args.command == "ledger":
        print(json.dumps(memory.ledger(limit=50), indent=2, default=str))
    elif args.command in ("session2", "session3"):
        # Detect and record the breach from fresh memory; never broadcasts.
        _run(memory, args.target, allow_attestation=False)
    elif args.command == "attest":
        # The deliberate, opt-in on-chain step: this broadcasts a real transaction.
        print(f"Attesting {args.target} on Base Sepolia (broadcasts a real transaction)...")
        _run(memory, args.target, allow_attestation=True)
    elif args.command == "check-deadlines":
        # Batch breach detection across all open commitments; never broadcasts.
        for ticket in memory.all():
            if ticket["phase"] != "CLOSED" and ticket["status"] != "resolved":
                AccountabilityRuntime(memory).process(ticket["ticket_id"])


if __name__ == "__main__":
    main()
