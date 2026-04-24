import logging
import os
from typing import Any

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import update

from app.core.config import settings
from app.db.session import async_session
from app.models.notification import UserDeviceToken, NotificationAudit

logger = logging.getLogger(__name__)


def _stringify_payload(data: dict[str, Any] | None) -> dict[str, str]:
    if not data:
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def _get_firebase_app():
    if not settings.FCM_ENABLED:
        logger.info("FCM is disabled by configuration.")
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logger.exception("firebase-admin is not installed. Push notifications are unavailable.")
        return None

    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    if settings.FIREBASE_PROJECT_ID and settings.FIREBASE_CLIENT_EMAIL and settings.FIREBASE_PRIVATE_KEY:
        private_key = settings.FIREBASE_PRIVATE_KEY.replace('\\n', '\n')
        cert_dict = {
            "type": "service_account",
            "project_id": settings.FIREBASE_PROJECT_ID,
            "private_key": private_key,
            "client_email": settings.FIREBASE_CLIENT_EMAIL,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        cred = credentials.Certificate(cert_dict)
        return firebase_admin.initialize_app(cred)

    service_account_file = settings.FCM_SERVICE_ACCOUNT_FILE
    if not service_account_file:
        logger.warning("FCM configuration is missing (no env vars or service account file). Push notifications are skipped.")
        return None

    if not os.path.exists(service_account_file):
        logger.warning("FCM service account file not found at path: %s", service_account_file)
        return None

    options = {}
    if settings.FCM_PROJECT_ID:
        options["projectId"] = settings.FCM_PROJECT_ID

    cred = credentials.Certificate(service_account_file)
    return firebase_admin.initialize_app(cred, options or None)


def send_push_to_tokens(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_tokens = [t.strip() for t in tokens if t and t.strip()]
    unique_tokens = list(dict.fromkeys(normalized_tokens))

    if not unique_tokens:
        return {"sent": 0, "failed": 0, "total": 0}

    app = _get_firebase_app()
    if app is None:
        return {"sent": 0, "failed": len(unique_tokens), "total": len(unique_tokens)}

    from firebase_admin import messaging

    payload = _stringify_payload(data)
    message = messaging.MulticastMessage(
        tokens=unique_tokens,
        notification=messaging.Notification(title=title, body=body),
        data=payload,
    )

    response = messaging.send_each_for_multicast(message, dry_run=settings.FCM_DRY_RUN, app=app)
    
    results = []
    failed_tokens = []
    
    for idx, item in enumerate(response.responses):
        token = unique_tokens[idx]
        success = item.success
        error_msg = str(item.exception) if item.exception else None
        
        # Determine if token should be invalidated based on common FCM exception codes
        is_invalid_token = False
        if not success and item.exception:
            # typical codes indicating dead token
            if getattr(item.exception, 'code', None) in ('NOT_FOUND', 'UNREGISTERED', 'INVALID_ARGUMENT'):
                is_invalid_token = True
                failed_tokens.append(token)
            elif 'request contains an invalid argument' in str(item.exception).lower() or 'not registered' in str(item.exception).lower():
                is_invalid_token = True
                failed_tokens.append(token)
            elif 'unregistered' in type(item.exception).__name__.lower():
                is_invalid_token = True
                failed_tokens.append(token)
                
        results.append({
            "token": token,
            "success": success,
            "error_message": error_msg,
            "is_invalid": is_invalid_token
        })

    if failed_tokens:
        logger.warning("Push send had failures for %s token(s) marked for cleanup.", len(failed_tokens))

    return {
        "sent": response.success_count,
        "failed": response.failure_count,
        "total": len(unique_tokens),
        "results": results,
    }

async def dispatch_push_notifications(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, Any] | None = None
) -> None:
    '''
    Async entrypoint for dispatching push notifications.
    It calls the FCM API and updates invalid tokens and saves audit records automatically.
    '''
    if not tokens:
        return
    
    result = await run_in_threadpool(
        send_push_to_tokens, tokens, title, body, data
    )

    results = result.get('results', [])
    if not results:
        return

    try:
        async with async_session() as db:
            invalid_tokens = [r['token'] for r in results if r.get('is_invalid', False)]
            if invalid_tokens:
                await db.execute(
                    update(UserDeviceToken)
                    .where(UserDeviceToken.token.in_(invalid_tokens))
                    .values(is_active=False)
                )
            
            audits = [
                NotificationAudit(
                    token=r['token'],
                    title=title[:255] if title else None,
                    body=body,
                    is_success=r['success'],
                    error_message=r.get('error_message')
                )
                for r in results
            ]
            db.add_all(audits)
            await db.commit()
    except Exception as e:
        logger.exception('Failed to process push notification audit and token invalidation')

