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

# Initialize face recognizer globally
try:
    face_recognizer = FaceRecognizer()
    logger.info("Face recognizer initialized in views")
except Exception as e:
    logger.error(f"Failed to initialize face recognizer in views: {e}")
    face_recognizer = None

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
        try:
            # Remove data URL prefix if present
            if ',' in image_data:
                image_data = image_data.split(',')[1]
            
            image_bytes = base64.b64decode(image_data)
            np_arr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            if img is None:
                return JsonResponse({'status': 'error', 'message': 'Invalid image data'}, status=400)
            
            logger.info(f"Image decoded successfully: {img.shape}")
            
        except Exception as e:
            logger.error(f"Error decoding image: {e}")
            return JsonResponse({'status': 'error', 'message': f'Error decoding image: {str(e)}'}, status=400)
        
        # Check if face recognizer is available
        if not face_recognizer:
            logger.error("Face recognizer not available")
            return JsonResponse({'status': 'error', 'message': 'Face recognition system not available'}, status=500)
        
        # Process based on session type
        try:
            if session.session_type == 'admin':
                logger.info(f"Processing admin verification for user {session.user_id}")
                verified, identity = face_recognizer.verify_admin_face(img, session.user_id)
                result = {'verified': verified, 'matric': None}
                logger.info(f"Admin verification result: {verified}")
                
            elif session.session_type == 'vote':
                logger.info("Processing voter verification")
                
                # Debug: Check loaded encodings
                logger.info(f"Loaded voter encodings: {len(face_recognizer.voter_encodings)}")
                for voter_id in face_recognizer.voter_encodings.keys():
                    logger.info(f"  - {voter_id}")
                
                verified, identity = face_recognizer.verify_voter_face(img)
                result = {'verified': verified, 'matric': identity}
                logger.info(f"Voter verification result: verified={verified}, identity={identity}")
                
            else:  # voter_registration
                if not matric:
                    return JsonResponse({'status': 'error', 'message': 'Matric number required for registration'}, status=400)
                
                logger.info(f"Processing voter registration for {matric}")
                
                # Check if voter exists in database
                if not Voter.objects.filter(matric_number=matric).exists():
                    return JsonResponse({'status': 'error', 'message': 'Voter not found in database'}, status=400)
                
                verified = face_recognizer.register_voter_face(img, matric)
                result = {'verified': verified, 'matric': matric}
                logger.info(f"Voter registration result: {verified}")
            
        except Exception as e:
            logger.error(f"Error in face processing: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'status': 'error', 'message': f'Face processing error: {str(e)}'}, status=500)
        
        # Update session
        session.status = 'completed'
        session.result = result
        session.save()
        
        logger.info(f"Session {session_id} completed with result: {result}")
        
        # Notify via WebSocket
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'verification_{session_id}',
                {
                    'type': 'status_update',
                    'status': 'completed',
                    'message': 'Verification completed'
                }
            )
        except Exception as e:
            logger.warning(f"WebSocket notification failed: {e}")
        
        return JsonResponse({
            'status': 'success',
            'verified': result['verified'],
            'message': 'Verification successful' if result['verified'] else 'Verification failed',
            'debug_info': {
                'session_type': session.session_type,
                'loaded_encodings': len(face_recognizer.voter_encodings) if face_recognizer else 0
            }
        })
        
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
