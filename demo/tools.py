"""Mock backend for "Velo Outdoor", a fictional outdoor-gear store, plus tool schemas.

Everything is in-memory and deterministic (except the optional injected failures)
so traces and experiment results are reproducible.
"""

from __future__ import annotations

import random
import zlib
from datetime import date, timedelta

from demo.config import tool_fail_rate

TODAY = date(2026, 9, 25)
REFUND_WINDOW_DAYS = 30


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


ORDERS: dict[str, dict] = {
    "VO-1001": {"customer": "u-alice", "item": "Summit 2P Tent", "sku": "TENT-2P", "amount": 329.00, "status": "delivered", "delivered_on": _d(5)},
    "VO-1002": {"customer": "u-bob", "item": "Trail Runner GTX (size 43)", "sku": "SHOE-TR43", "amount": 149.00, "status": "shipped", "carrier": "UPS", "tracking": "1Z999AA10123456784", "eta": _d(-2)},
    "VO-1003": {"customer": "u-carol", "item": "Down Jacket 800FP", "sku": "JKT-DN800", "amount": 279.00, "status": "delivered", "delivered_on": _d(52)},
    "VO-1004": {"customer": "u-dave", "item": "Ultralight Stove", "sku": "STOVE-UL", "amount": 59.00, "status": "processing"},
    "VO-1005": {"customer": "u-erin", "item": "Headlamp 400lm", "sku": "LAMP-400", "amount": 39.00, "status": "delivered", "delivered_on": _d(12), "note": "arrived damaged per customer photo"},
    "VO-1006": {"customer": "u-frank", "item": "Sleeping Bag -10C", "sku": "BAG-M10", "amount": 219.00, "status": "delivered", "delivered_on": _d(75)},
    "VO-1007": {"customer": "u-grace", "item": "Carbon Trekking Poles", "sku": "POLE-CB", "amount": 129.00, "status": "cancelled"},
    "VO-1008": {"customer": "u-heidi", "item": "Water Filter", "sku": "FILT-01", "amount": 45.00, "status": "delivered", "delivered_on": _d(31)},
}

INVENTORY: dict[str, dict] = {
    "TENT-2P": {"name": "Summit 2P Tent", "in_stock": 14, "price": 329.00},
    "TENT-3P": {"name": "Summit 3P Tent", "in_stock": 0, "price": 399.00, "restock": _d(-10)},
    "SHOE-TR43": {"name": "Trail Runner GTX size 43", "in_stock": 3, "price": 149.00},
    "SHOE-TR44": {"name": "Trail Runner GTX size 44", "in_stock": 0, "price": 149.00, "restock": _d(-21)},
    "JKT-DN800": {"name": "Down Jacket 800FP", "in_stock": 22, "price": 279.00},
    "LAMP-400": {"name": "Headlamp 400lm", "in_stock": 60, "price": 39.00},
    "BAG-M10": {"name": "Sleeping Bag -10C", "in_stock": 7, "price": 219.00},
}

KB: list[dict] = [
    {"id": "kb-returns", "title": "Returns & refunds", "text": f"Items can be returned for a full refund within {REFUND_WINDOW_DAYS} days of delivery. After {REFUND_WINDOW_DAYS} days we offer store credit only. Damaged items are refunded regardless of date. Refunds reach the original payment method in 5-7 business days."},
    {"id": "kb-shipping", "title": "Shipping", "text": "Standard shipping is free over $75 and takes 3-5 business days. Express shipping costs $15 and takes 1-2 business days. We ship with UPS."},
    {"id": "kb-warranty", "title": "Warranty", "text": "Tents, jackets and sleeping bags carry a 2-year warranty against manufacturing defects. Warranty claims go to a human specialist."},
    {"id": "kb-sizing", "title": "Shoe sizing", "text": "Trail Runner GTX runs half a size small; we recommend ordering half a size up."},
    {"id": "kb-cancel", "title": "Cancellations", "text": "Orders can be cancelled free of charge while in 'processing' status. Once shipped, use the returns process."},
]


class ToolError(Exception):
    pass


def _maybe_fail(tool: str) -> None:
    if random.random() < tool_fail_rate():
        raise ToolError(f"{tool}: upstream service timeout (503)")


def lookup_order(order_id: str) -> dict:
    _maybe_fail("lookup_order")
    order = ORDERS.get(order_id.strip().upper())
    if not order:
        raise ToolError(f"order {order_id} not found")
    return {"order_id": order_id.upper(), **order}


def search_kb(query: str) -> list[dict]:
    _maybe_fail("search_kb")
    words = {w for w in query.lower().split() if len(w) > 2}
    scored = sorted(
        KB,
        key=lambda a: -sum(w in (a["title"] + " " + a["text"]).lower() for w in words),
    )
    return scored[:2]


def check_inventory(sku: str) -> dict:
    _maybe_fail("check_inventory")
    item = INVENTORY.get(sku.strip().upper())
    if not item:
        raise ToolError(f"unknown sku {sku}; known skus: {', '.join(INVENTORY)}")
    return {"sku": sku.upper(), **item}


def issue_refund(order_id: str, reason: str) -> dict:
    _maybe_fail("issue_refund")
    oid = order_id.strip().upper()
    order = ORDERS.get(oid)
    if not order:
        raise ToolError(f"order {order_id} not found")
    if order["status"] != "delivered":
        raise ToolError(f"order {oid} is '{order['status']}', only delivered orders can be refunded")
    age = (TODAY - date.fromisoformat(order["delivered_on"])).days
    damaged = "damag" in (reason + order.get("note", "")).lower()
    # The backend does NOT enforce the refund window: that is the agent's job
    # (and exactly what the evaluation checks).
    return {
        "order_id": oid,
        "refunded": order["amount"],
        "days_since_delivery": age,
        "within_policy": age <= REFUND_WINDOW_DAYS or damaged,
        "reference": f"RF-{oid[-4:]}",
    }


def cancel_order(order_id: str) -> dict:
    _maybe_fail("cancel_order")
    oid = order_id.strip().upper()
    order = ORDERS.get(oid)
    if not order:
        raise ToolError(f"order {order_id} not found")
    if order["status"] != "processing":
        raise ToolError(f"order {oid} is '{order['status']}', only processing orders can be cancelled")
    # Like issue_refund, nothing is mutated, so every session sees the same data.
    return {"order_id": oid, "cancelled": True, "refunded": order["amount"], "reference": f"CX-{oid[-4:]}"}


def escalate_to_human(summary: str) -> dict:
    # crc32, not hash(): str hashes are salted per process, so tickets would change run to run.
    return {"ticket": f"HUM-{zlib.crc32(summary.encode()) % 10000:04d}", "eta": "within 4 business hours"}


TOOL_FUNCS = {
    "lookup_order": lookup_order,
    "search_kb": search_kb,
    "check_inventory": check_inventory,
    "issue_refund": issue_refund,
    "cancel_order": cancel_order,
    "escalate_to_human": escalate_to_human,
}

# Provider-neutral schemas; llm.py converts them to Anthropic / OpenAI formats.
TOOL_SPECS: list[dict] = [
    {
        "name": "lookup_order",
        "description": "Get status, item, amount and delivery date of an order by its ID (format VO-1234).",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Order ID, e.g. VO-1001"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_kb",
        "description": "Search the help-center knowledge base (returns, shipping, warranty, sizing, cancellations).",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_inventory",
        "description": "Check stock level, price and restock date for a SKU. Known SKUs: " + ", ".join(INVENTORY),
        "parameters": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
            "additionalProperties": False,
        },
    },
    {
        "name": "issue_refund",
        "description": "Issue a refund to the original payment method. This moves money and cannot be undone.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "reason": {"type": "string", "description": "Customer's reason for the refund"},
            },
            "required": ["order_id", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_order",
        "description": "Cancel an order that is still in 'processing' status, free of charge. Shipped or delivered orders cannot be cancelled.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Hand the conversation to a human support specialist.",
        "parameters": {
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "Short summary of the issue"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
]
