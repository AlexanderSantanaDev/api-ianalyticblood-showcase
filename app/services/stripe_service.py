import stripe
import logging
from app.core.config import settings
from app.services.db_service import get_user_by_email, update_user_profile

# Configuración de logs
logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

# ID del precio en Stripe
PREMIUM_PRICE_ID = settings.STRIPE_PRICE_ID_PREMIUM or "price_default_premium"

async def create_checkout_session(user_id: str, email: str, plan: str):
    """ Crea una sesión de Checkout para el usuario """
    try:
        # 1. Obtenemos el cliente o lo creamos
        user = await get_user_by_email(email)
        customer_id = user.get("stripe_customer_id")
        
        # Validar si el cliente aún existe en Stripe (por si fue borrado manualmente)
        if customer_id:
            try:
                stripe_cust = stripe.Customer.retrieve(customer_id)
                if getattr(stripe_cust, "deleted", False):
                    print(f"⚠️ Cliente {customer_id} estaba borrado en Stripe. Creando uno nuevo...")
                    customer_id = None
            except stripe.error.InvalidRequestError:
                print(f"⚠️ Cliente {customer_id} no existe en Stripe. Creando uno nuevo...")
                customer_id = None

        if not customer_id:
            customer = stripe.Customer.create(
                email=email,
                name=user.get("name"),
                metadata={"user_id": user_id}
            )
            customer_id = customer.id
            await update_user_profile(user_id, {"stripe_customer_id": customer_id})

        # URLs dinámicas según entorno (local vs producción)
        success_url = f"{settings.FRONTEND_URL}/dashboard/subscription?success=true"
        cancel_url = f"{settings.FRONTEND_URL}/dashboard/subscription?canceled=true"

        # 3. Creamos la sesión
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price": PREMIUM_PRICE_ID,
                    "quantity": 1,
                },
            ],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": user_id,
                "plan": plan
            }
        )
        return session.url
    except Exception as e:
        print(f"❌ Error al crear sesión de checkout: {e}")
        return None

async def create_portal_session(customer_id: str):
    """ Crea una sesión para el portal de facturación de Stripe """
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{settings.FRONTEND_URL}/dashboard/subscription"
        )
        return session.url
    except Exception as e:
        print(f"❌ Error al crear sesión del portal: {e}")
        return None

async def sync_user_subscription(email: str):
    """ Consulta a Stripe exhaustivamente y actualiza el plan del usuario en la DB """
    print(f"\n--- 🔄 INICIANDO SINCRONIZACIÓN PARA: {email} ---")
    try:
        user = await get_user_by_email(email)
        if not user:
            print(f"❌ Usuario no encontrado en la base de datos local: {email}")
            return False
            
        print(f"🔍 Buscando clientes en Stripe asociados a: {email}")
        customers = stripe.Customer.list(email=email, limit=10)
        
        if not customers.data:
            print(f"⚠️ No hay perfiles de cliente en Stripe para este email.")
            return False

        found_subscription = None
        active_customer_id = None
        
        print(f"📊 Encontrados {len(customers.data)} clientes en Stripe. Escaneando...")
        for stripe_customer in customers.data:
            print(f"   👉 Revisando ID: {stripe_customer.id}...")
            # Revisamos tanto 'active' como 'trialing' por si acaso
            subscriptions = stripe.Subscription.list(
                customer=stripe_customer.id, 
                limit=10
            )
            
            for sub in subscriptions.data:
                print(f"      🔹 Encontrada suscripción: {sub.id} [Status: {sub.status}]")
                if sub.status in ["active", "trialing"]:
                    found_subscription = sub
                    active_customer_id = stripe_customer.id
                    break
            
            if found_subscription:
                break
                
        if found_subscription:
            print(f"✅ ¡SUSCRIPCIÓN PREMIUM ENCONTRADA! Actualizando usuario...")
            await update_user_profile(user["id"], {
                "plan": "premium",
                "subscription_status": found_subscription.status,
                "stripe_customer_id": active_customer_id,
                "stripe_subscription_id": found_subscription.id,
                "cancel_at_period_end": found_subscription.get("cancel_at_period_end", False),
                "current_period_end": found_subscription.get("current_period_end", None)
            })
            print(f"✨ ÉXITO: Usuario actualizado a Premium en MongoDB.")
            return "premium"  # Retorna string descriptivo
        else:
            print(f"❌ No se encontró ninguna suscripción activa o en periodo de prueba.")
            # Si después de buscar en todos los perfiles no hay nada activo, siempre bajamos a free
            # aunque el usuario ya estuviera en free (para limpiar datos stale)
            await update_user_profile(user["id"], {
                "plan": "free",
                "subscription_status": "inactive",
                "cancel_at_period_end": False,
                "current_period_end": None
            })
            print(f"✨ Usuario degradado/confirmado como Free en MongoDB.")
            return "free"  # Siempre retorna 'free' para que el frontend lo detecte
            
    except Exception as e:
        print(f"🚨 ERROR CRÍTICO EN SINCRONIZACIÓN: {e}")
        logger.error(f"Error en sincronización profunda para {email}: {e}")
        return False



#  Cancelación suave - el usuario mantiene Premium hasta el final del periodo
async def cancel_subscription_at_period_end(subscription_id: str, user_id: str):
    """
    Cancela la suscripción al final del periodo de facturación actual.
    El usuario mantiene acceso Premium hasta que expire el periodo.
    """
    try:
        print(f"\n--- 🚫 CANCELANDO SUSCRIPCIÓN: {subscription_id} (al final del periodo) ---")
        
        # Llamada a Stripe: cancel_at_period_end=True, no cancela de inmediato
        subscription = stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True
        )
        
        period_end = subscription.get("current_period_end")
        
        # Actualizamos MongoDB con el estado de cancelación pendiente
        await update_user_profile(user_id, {
            "cancel_at_period_end": True,
            "current_period_end": period_end,
            "subscription_status": subscription.get("status", "active")
        })
        
        print(f"✅ Suscripción marcada para cancelar al final del periodo: {period_end}")
        return {"current_period_end": period_end}
        
    except stripe.error.InvalidRequestError as e:
        print(f"❌ Error de Stripe al cancelar: {e}")
        return None
    except Exception as e:
        print(f"🚨 Error inesperado al cancelar suscripción: {e}")
        logger.error(f"Error al cancelar suscripción {subscription_id}: {e}")
        return None


# Reactivación - revierte una cancelación pendiente antes de que expire
async def reactivate_subscription(subscription_id: str, user_id: str):
    """
    Reactiva una suscripción que estaba marcada para cancelarse al final del periodo.
    Solo funciona si el periodo aún no ha expirado.
    """
    try:
        print(f"\n--- 🔄 REACTIVANDO SUSCRIPCIÓN: {subscription_id} ---")
        
        # Llamada a Stripe: cancel_at_period_end=False revierte la cancelación
        subscription = stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=False
        )
        
        # Actualizamos MongoDB: la suscripción vuelve a estar activa normalmente
        await update_user_profile(user_id, {
            "cancel_at_period_end": False,
            "subscription_status": subscription.get("status", "active")
        })
        
        print(f"✅ Suscripción reactivada correctamente.")
        return {"status": subscription.get("status")}
        
    except stripe.error.InvalidRequestError as e:
        print(f"❌ Error de Stripe al reactivar: {e}")
        return None
    except Exception as e:
        print(f"🚨 Error inesperado al reactivar suscripción: {e}")
        logger.error(f"Error al reactivar suscripción {subscription_id}: {e}")
        return None
