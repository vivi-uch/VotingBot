#!/usr/bin/env python
"""
Debug face verification issues
"""
import os
import sys
import django
import cv2
import numpy as np

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'evoting.settings')
django.setup()

from django.conf import settings
from bot.models import Voter
from bot.services.face_recognition import FaceRecognizer

def check_face_encodings():
    """Check if face encodings are properly saved and loaded"""
    print("🔍 Checking Face Encodings")
    print("=" * 40)
    
    # Check voter encodings directory
    voter_encodings_path = os.path.join(settings.FACE_DATA_PATH, 'voters')
    print(f"Voter encodings path: {voter_encodings_path}")
    
    if not os.path.exists(voter_encodings_path):
        print("❌ Voter encodings directory doesn't exist")
        return False
    
    # List encoding files
    encoding_files = [f for f in os.listdir(voter_encodings_path) if f.endswith('.npy')]
    print(f"Found {len(encoding_files)} encoding files:")
    
    for file in encoding_files:
        matric = file.replace('.npy', '')
        file_path = os.path.join(voter_encodings_path, file)
        
        try:
            # Try to load the encoding
            encoding = np.load(file_path)
            print(f"  ✅ {matric}: {encoding.shape} - {file_path}")
            
            # Check if voter exists in database
            voter_exists = Voter.objects.filter(matric_number=matric).exists()
            print(f"     Database: {'✅ Exists' if voter_exists else '❌ Missing'}")
            
        except Exception as e:
            print(f"  ❌ {matric}: Error loading - {e}")
    
    return len(encoding_files) > 0

def test_face_recognizer_loading():
    """Test if FaceRecognizer can load encodings"""
    print("\n🤖 Testing FaceRecognizer Loading")
    print("=" * 40)
    
    try:
        face_recognizer = FaceRecognizer()
        print(f"✅ FaceRecognizer initialized")
        print(f"   Voter encodings loaded: {len(face_recognizer.voter_encodings)}")
        print(f"   Admin encodings loaded: {len(face_recognizer.admin_encodings)}")
        
        # List loaded voter encodings
        if face_recognizer.voter_encodings:
            print("   Loaded voter IDs:")
            for voter_id in face_recognizer.voter_encodings.keys():
                print(f"     • {voter_id}")
        else:
            print("   ❌ No voter encodings loaded")
        
        return face_recognizer
    except Exception as e:
        print(f"❌ Error initializing FaceRecognizer: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_live_verification():
    """Test live face verification"""
    print("\n📸 Testing Live Face Verification")
    print("=" * 40)
    
    face_recognizer = test_face_recognizer_loading()
    if not face_recognizer:
        return
    
    if not face_recognizer.voter_encodings:
        print("❌ No voter encodings available for testing")
        return
    
    print("Starting webcam for verification test...")
    print("Press SPACE to capture and test, ESC to cancel")
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Cannot access webcam")
        return
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        cv2.imshow('Face Verification Test - Press SPACE to test, ESC to exit', frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' '):  # Space key
            print("📸 Testing face verification...")
            
            try:
                # Test face detection
                face, bbox = face_recognizer.detect_and_align_face(frame)
                if face is None:
                    print("❌ No face detected")
                    continue
                
                print("✅ Face detected")
                
                # Test face verification
                verified, identity = face_recognizer.verify_voter_face(frame)
                
                if verified:
                    print(f"✅ Verification successful! Identity: {identity}")
                else:
                    print("❌ Verification failed - no matching voter found")
                    
                    # Show distances to all registered voters
                    embedding = face_recognizer.generate_embedding(face)
                    if embedding is not None:
                        print("   Distances to registered voters:")
                        from scipy import spatial
                        for voter_id, voter_embedding in face_recognizer.voter_encodings.items():
                            dist = spatial.distance.cosine(embedding, voter_embedding)
                            print(f"     • {voter_id}: {dist:.4f} {'✅' if dist < 0.4 else '❌'}")
                
            except Exception as e:
                print(f"❌ Verification error: {e}")
                import traceback
                traceback.print_exc()
        
        elif key == 27:  # ESC key
            break
    
    cap.release()
    cv2.destroyAllWindows()

def check_verification_web_interface():
    """Check if the web interface is working"""
    print("\n🌐 Checking Web Interface")
    print("=" * 40)
    
    try:
        import requests
        
        # Test if Django server is running
        test_url = f"{settings.BASE_URL}/verification/capture/test-session-id/"
        print(f"Testing URL: {test_url}")
        
        try:
            response = requests.get(test_url, timeout=5)
            print(f"✅ Web server responding: {response.status_code}")
        except requests.exceptions.ConnectionError:
            print("❌ Web server not running")
            print("   Please run: python manage.py runserver")
        except Exception as e:
            print(f"⚠️ Web server test failed: {e}")
        
    except Exception as e:
        print(f"❌ Error testing web interface: {e}")

def main():
    print("🔧 Face Verification Debug Tool")
    print("=" * 50)
    
    # Step 1: Check face encodings
    encodings_ok = check_face_encodings()
    
    # Step 2: Test FaceRecognizer
    face_recognizer = test_face_recognizer_loading()
    
    # Step 3: Check web interface
    check_verification_web_interface()
    
    # Step 4: Offer live test
    if encodings_ok and face_recognizer:
        print("\n" + "=" * 50)
        test_live = input("Do you want to test live face verification? (y/n): ").lower()
        if test_live == 'y':
            test_live_verification()
    
    print("\n" + "=" * 50)
    print("🔧 Troubleshooting Tips:")
    print("1. Make sure you registered your face with the exact same matric number")
    print("2. Ensure good lighting when capturing face")
    print("3. Look directly at the camera")
    print("4. Make sure the Django web server is running")
    print("5. Check that the face recognition models are properly installed")

if __name__ == '__main__':
    main()
