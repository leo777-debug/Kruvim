"""Authenticated checkout/portal endpoints and a signature-verified public webhook."""
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, principal, role
from app.core.config import settings
from app.core.errors import AppError, Forbidden
from app.db.session import get_session
from app.services import billing

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutIn(BaseModel):
    kind: Literal["subscription", "topup"]
    seats: int = Field(default=1, ge=1, le=1000)


@router.get("")
async def billing_status(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    state = await billing.status(s, p.org_id, p.seat_user_id)
    await s.commit()
    return state


@router.post("/checkout")
async def checkout(body: CheckoutIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    return await billing.checkout(s, p, body.kind, body.seats)


@router.post("/portal")
async def portal(p: Principal = Depends(role("owner")), s: AsyncSession = Depends(get_session)):
    if p.via != "session":
        raise Forbidden("Sign in as the workspace owner to manage billing.")
    a = await billing.account(s, p.org_id)
    if not a.customer_id:
        raise AppError("Subscribe before opening the billing portal.")
    result = await billing.dodo("POST", "/customers/" + quote(a.customer_id, safe="") + "/customer-portal/session",
        params={"send_email": "false", "return_url": settings.public_app_url + "/usage"})
    await s.commit()
    return {"url": billing.safe_url(result.get("link"))}


@router.post("/webhook")
async def webhook(request: Request, s: AsyncSession = Depends(get_session)):
    if not settings.billing_enabled or not billing.configured():
        raise AppError("Payments are not configured.", status=503)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1_000_000:
            raise AppError("Payment webhook too large.", status=413)
    event_id, payload = billing.verify_webhook(bytes(raw), request.headers)
    try:
        await billing.process_webhook(s, event_id, payload)
    except (KeyError, ValueError, TypeError):
        await s.rollback()
        raise AppError("Payment event could not be processed. Please retry.", status=503, code="billing_event_invalid")
    return {"received": True}
