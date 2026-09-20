import asyncio
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from ..models import Usuario
from ..api.router_auth import send_membership_expiration_reminder


async def run_membership_reminder_loop(session_factory: sessionmaker, interval_seconds: int = 86400):
    """Send one reminder while an approved paid membership is within three days of expiry."""
    while True:
        db = session_factory()
        try:
            now = datetime.utcnow()
            reminder_limit = now + timedelta(days=3)
            users = (
                db.query(Usuario)
                .filter(
                    Usuario.membership_expiration.isnot(None),
                    Usuario.membership_expiration >= now,
                    Usuario.membership_expiration <= reminder_limit,
                    Usuario.payment_status == 'approved',
                )
                .all()
            )

            for user in users:
                reminder_cutoff = user.membership_expiration - timedelta(days=3)
                if user.membership_reminder_sent_at and user.membership_reminder_sent_at >= reminder_cutoff:
                    continue

                try:
                    await asyncio.to_thread(send_membership_expiration_reminder, user)
                except Exception as error:
                    print(f'No se pudo enviar recordatorio a {user.correo}: {error}')
                    continue

                user.membership_reminder_sent_at = datetime.utcnow()
                db.add(user)

            db.commit()
        except Exception as error:
            db.rollback()
            print(f'Error en tarea de recordatorios de membresía: {error}')
        finally:
            db.close()

        await asyncio.sleep(interval_seconds)
