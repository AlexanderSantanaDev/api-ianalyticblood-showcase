from fastapi import APIRouter, Depends, HTTPException, Request, Header
from app.core.security import get_current_user, get_current_user_from_db
from app.services.stripe_service import create_checkout_session, create_portal_session, sync_user_subscription, cancel_subscription_at_period_end, reactivate_subscription
from app.services.db_service import update_user_profile, get_user_by_stripe_customer_id
from app.core.config import settings
import stripe

router = APIRouter()

@router.post("/create-checkout")
async def create_checkout(plan: str, current_user: dict = Depends(get_current_user)):
    """ Crea una sesión de Checkout de Stripe """
    if plan not in ["premium", "enterprise"]:
        raise HTTPException(status_code=400, detail="Plan inválido")
    
    checkout_url = await create_checkout_session(
        user_id=current_user["id"],
        email=current_user["email"],
        plan=plan
    )
    
    if not checkout_url:
        raise HTTPException(status_code=500, detail="Error al crear sesión de pago")
        
    return {"url": checkout_url}

@router.get("/sync")
async def sync_subscription(current_user: dict = Depends(get_current_user)):
    """ Sincroniza manualmente el estado de la suscripción con Stripe """
    result = await sync_user_subscription(current_user["email"])
    # Resultado descriptivo para que el frontend sepa si hubo cambio
    if result == "premium":
        return {"status": "success", "plan": "premium"}
    elif result == "free":
        return {"status": "success", "plan": "free"}
    else:
        return {"status": "no_change"}

@router.post("/customer-portal")
async def customer_portal(current_user: dict = Depends(get_current_user_from_db)):
    # Usa get_current_user_from_db porque necesita stripe_customer_id (no está en JWT)
    """ Crea una sesión del portal de cliente de Stripe """
    customer_id = current_user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="No tienes una suscripción activa")
        
    portal_url = await create_portal_session(customer_id)
    if not portal_url:
        raise HTTPException(status_code=500, detail="Error al crear portal de cliente")
        
    return {"url": portal_url}

# 🔒 Endpoint de cancelación: cancela al final del periodo de facturación, no de forma inmediata
@router.post("/cancel")
async def cancel_subscription(current_user: dict = Depends(get_current_user_from_db)):
    """
    Marca la suscripción para cancelarse al final del periodo actual.
    El usuario mantiene acceso Premium hasta la fecha de renovación.
    """
    subscription_id = current_user.get("stripe_subscription_id")
    user_id = current_user.get("id")

    if not subscription_id:
        raise HTTPException(status_code=400, detail="No tienes ninguna suscripción activa")

    result = await cancel_subscription_at_period_end(subscription_id, user_id)
    if not result:
        raise HTTPException(status_code=500, detail="Error al cancelar la suscripción")

    return {
        "status": "success",
        "message": "Tu suscripción se cancelará al final del periodo de facturación.",
        "cancel_at_period_end": True,
        "current_period_end": result.get("current_period_end")
    }

# Endpoint de reactivación: revierte una cancelación pendiente
@router.post("/reactivate")
async def reactivate_subscription_endpoint(current_user: dict = Depends(get_current_user_from_db)):
    """
    Reactiva una suscripción que estaba marcada para cancelarse.
    """
    subscription_id = current_user.get("stripe_subscription_id")
    user_id = current_user.get("id")

    if not subscription_id:
        raise HTTPException(status_code=400, detail="No tienes ninguna suscripción activa")

    result = await reactivate_subscription(subscription_id, user_id)
    if not result:
        raise HTTPException(status_code=500, detail="Error al reactivar la suscripción")

    return {
        "status": "success",
        "message": "¡Tu suscripción Premium ha sido reactivada!",
        "cancel_at_period_end": False
    }

@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """ Maneja los Webhooks de Stripe para actualizar suscripciones """
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Payload inválido")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Firma de webhook inválida")

    # Manejar el evento
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_id = session.get("customer")
        user_id = session.get("metadata", {}).get("user_id")
        plan = session.get("metadata", {}).get("plan", "premium")
        
        if user_id:
            await update_user_profile(user_id, {
                "plan": plan,
                "subscription_status": "active",
                "stripe_subscription_id": session.get("subscription")
            })

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        user = await get_user_by_stripe_customer_id(customer_id)
        if user:
            await update_user_profile(user["id"], {
                "plan": "free",
                "subscription_status": "canceled",
                "cancel_at_period_end": False,
                "current_period_end": None
            })

    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        user = await get_user_by_stripe_customer_id(customer_id)
        if user:
            cancel_at_period_end = subscription.get("cancel_at_period_end", False)
            current_period_end = subscription.get("current_period_end", None)
            
            # Si el status cambia a canceled o incomplete_expired, lo marcamos free
            if subscription.get("status") in ["canceled", "incomplete_expired", "past_due", "unpaid"]:
                await update_user_profile(user["id"], {
                    "plan": "free",
                    "subscription_status": subscription.get("status"),
                    "cancel_at_period_end": False,
                    "current_period_end": None
                })
            else:
                await update_user_profile(user["id"], {
                    "subscription_status": subscription.get("status"),
                    "cancel_at_period_end": cancel_at_period_end,
                    "current_period_end": current_period_end
                })

    return {"status": "success"}

