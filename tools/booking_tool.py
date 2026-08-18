"""
tools/booking_tool.py

Stub implementations for the Booking Agent. These let the app boot and
the approve -> payment-interrupt -> confirm flow run end-to-end for a
demo, without touching a real payment provider.

TODO before this goes anywhere near real money:
- reserve_flight / reserve_hotel: wire up to whatever your flight/hotel
  provider actually supports for holds (AviationStack itself doesn't
  do bookings — you'd need a separate booking-capable API, or treat
  this as "prepare the exact booking payload" rather than a real hold).
- charge_payment: wire up to Stripe/Razorpay. This must be the ONLY
  function in the codebase that touches a payment provider, and it
  should only ever be called from backend.confirm_payment(), which
  itself only runs after interrupt() has been resumed by a real user
  action via POST /api/travel/confirm-payment.
"""

import re


def _extract_price(text: str, default: float = 0.0) -> float:
    """
    Best-effort price extraction from free-text search results.
    flight_results / hotel_results are currently plain strings from
    search_flights() / tavily_search(), not structured data, so this
    is a rough placeholder — consider having those tools return
    structured JSON (price, provider, etc.) instead of text so this
    doesn't have to guess.
    """
    match = re.search(r"[₹$]\s?([\d,]+(?:\.\d+)?)", text or "")
    if not match:
        return default
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return default


def reserve_flight(flight_results: str) -> dict:
    price = _extract_price(flight_results, default=4500.0)
    return {
        "summary": (flight_results or "Flight reserved.")[:200],
        "price": price,
        "reserved": True,
    }


def reserve_hotel(hotel_results: str) -> dict:
    price = _extract_price(hotel_results, default=2500.0)
    return {
        "summary": (hotel_results or "Hotel reserved.")[:200],
        "price": price,
        "reserved": True,
    }


def charge_payment(booking_summary: str) -> dict:
    """
    Mock payment — always succeeds. Replace with a real Stripe/Razorpay
    charge before this is used for anything but a demo.
    """
    return {
        "success": True,
        "message": f"Payment confirmed.\n\n{booking_summary}",
    }