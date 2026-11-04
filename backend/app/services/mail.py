"""Notification provider hook. Development uses a console backend, never fake delivery."""
import logging


async def notify(user_id, subject, body):
    logging.getLogger('kruvim.mail').info('Email notification queued for console delivery',
        extra={'recipient_user_id': user_id, 'subject': subject, 'delivery_backend': 'console'})
