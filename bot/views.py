import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import VerificationSession

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["POST"])
def webhook(request):
    """
    Webhook endpoint for Telegram updates.
    This is used when running the bot in webhook mode instead of polling.
    """
    try:
        data = json.loads(request.body)
        logger.info(f"Received webhook data: {data}")
        # Process webhook data (can be implemented later)
        return JsonResponse({"status": "success"})
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@require_http_methods(["GET"])
def session_result(request, session_id):
    """
    Get the result of a verification session.
    Used by the Telegram bot to check if a session is complete.
    """
    try:
        session = get_object_or_404(VerificationSession, id=session_id)
        
        # Check if session is expired
        if session.is_expired() and session.status == 'pending':
            session.status = 'expired'
            session.save()
        
        return JsonResponse({
            "status": session.status,
            "result": session.result,
            "session_type": session.session_type,
            "user_id": session.user_id,
        })
    except Exception as e:
        logger.error(f"Error getting session result: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@csrf_exempt
@require_http_methods(["POST"])
def update_session(request, session_id):
    """
    Update a verification session with results.
    Used by the verification app to update session status.
    """
    try:
        session = get_object_or_404(VerificationSession, id=session_id)
        data = json.loads(request.body)
        
        session.status = 'completed'
        session.result = data
        session.save()
        
        logger.info(f"Updated session {session_id} with result: {data}")
        return JsonResponse({"status": "success"})
    except Exception as e:
        logger.error(f"Error updating session: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
