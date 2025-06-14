import json
import logging
import numpy as np
import cv2
import base64
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from bot.models import VerificationSession, Voter, Admin
from bot.services.face_recognition import FaceRecognizer

logger = logging.getLogger(__name__)
face_recognizer = FaceRecognizer()

def capture_face(request, session_id):
    """
    Render the face capture page for a verification session
    """
    session = get_object_or_404(VerificationSession, id=session_id)
    
    # Check if session is expired
    if session.is_expired():
        session.status = 'expired'
        session.save()
        return render(request, 'verification/expired.html')
    
    context = {
        'session': session,
        'session_id': session_id,
        'session_type': session.session_type,
    }
    
    return render(request, 'verification/capture.html', context)

@csrf_exempt
@require_http_methods(["POST"])
def process_image(request, session_id):
    """
    Process a captured face image for verification or registration
    """
    try:
        session = get_object_or_404(VerificationSession, id=session_id)
        
        # Check if session is expired
        if session.is_expired():
            session.status = 'expired'
            session.save()
            return JsonResponse({'status': 'error', 'message': 'Session expired'}, status=400)
        
        # Get image data from request
        data = json.loads(request.body)
        image_data = data.get('image')
        matric = data.get('matric')
        
        if not image_data:
            return JsonResponse({'status': 'error', 'message': 'No image data provided'}, status=400)
        
        # Convert base64 to image
        image_data = image_data.split(',')[1]
        image_bytes = base64.b64decode(image_data)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if img is None:
            return JsonResponse({'status': 'error', 'message': 'Invalid image data'}, status=400)
        
        # Process based on session type
        if session.session_type == 'admin':
            verified, identity = face_recognizer.verify_admin_face(img, session.user_id)
            result = {'verified': verified, 'matric': None}
        elif session.session_type == 'vote':
            verified, identity = face_recognizer.verify_voter_face(img)
            result = {'verified': verified, 'matric': identity}
        else:  # voter_registration
            if not matric:
                return JsonResponse({'status': 'error', 'message': 'Matric number required for registration'}, status=400)
            
            # Check if voter exists in database
            if not Voter.objects.filter(matric_number=matric).exists():
                return JsonResponse({'status': 'error', 'message': 'Voter not found in database'}, status=400)
            
            verified = face_recognizer.register_voter_face(img, matric)
            result = {'verified': verified, 'matric': matric}
        
        # Update session
        session.status = 'completed'
        session.result = result
        session.save()
        
        # Notify via WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'verification_{session_id}',
            {
                'type': 'status_update',
                'status': 'completed',
                'message': 'Verification completed'
            }
        )
        
        return JsonResponse({
            'status': 'success',
            'verified': result['verified'],
            'message': 'Verification successful' if result['verified'] else 'Verification failed'
        })
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
