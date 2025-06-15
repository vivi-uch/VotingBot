#!/usr/bin/env python
"""
Script to register voter face encodings
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

def capture_face_from_webcam():
    """Capture face from webcam"""
    print("📸 Starting webcam for face capture...")
    print("Press SPACE to capture, ESC to cancel")
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Cannot access webcam")
        return None
    
    captured_image = None
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ Failed to capture frame")
            break
        
        # Display the frame
        cv2.imshow('Voter Face Registration - Press SPACE to capture, ESC to cancel', frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' '):  # Space key
            captured_image = frame.copy()
            print("✅ Image captured!")
            break
        elif key == 27:  # ESC key
            print("❌ Capture cancelled")
            break
    
    cap.release()
    cv2.destroyAllWindows()
    return captured_image

def load_face_from_file(image_path):
    """Load face from image file"""
    if not os.path.exists(image_path):
        print(f"❌ Image file not found: {image_path}")
        return None
    
    image = cv2.imread(image_path)
    if image is None:
        print(f"❌ Failed to load image: {image_path}")
        return None
    
    print(f"✅ Image loaded from: {image_path}")
    return image

def main():
    print("🗳️ Voter Face Registration")
    print("=" * 30)
    
    # Get voter matric number
    matric_number = input("Enter voter matric number: ").strip()
    
    if not matric_number:
        print("❌ Matric number cannot be empty")
        return
    
    # Check if voter exists in database
    try:
        if not Voter.objects.filter(matric_number=matric_number).exists():
            print(f"❌ Voter {matric_number} not found in database")
            create = input("Do you want to create this voter? (y/n): ").lower()
            if create == 'y':
                Voter.objects.create(matric_number=matric_number)
                print(f"✅ Voter {matric_number} created")
            else:
                return
    except Exception as e:
        print(f"❌ Database error: {e}")
        return
    
    # Choose input method
    print("\nChoose face input method:")
    print("1. Capture from webcam")
    print("2. Load from image file")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    image = None
    if choice == '1':
        image = capture_face_from_webcam()
    elif choice == '2':
        image_path = input("Enter path to image file: ").strip()
        image = load_face_from_file(image_path)
    else:
        print("❌ Invalid choice")
        return
    
    if image is None:
        print("❌ No image captured/loaded")
        return
    
    # Initialize face recognizer
    try:
        print("🔍 Initializing face recognizer...")
        face_recognizer = FaceRecognizer()
        print("✅ Face recognizer initialized")
    except Exception as e:
        print(f"❌ Failed to initialize face recognizer: {e}")
        return
    
    # Register the face
    try:
        print("🔍 Processing face...")
        
        # Use the register_voter_face method
        success = face_recognizer.register_voter_face(image, matric_number)
        
        if success:
            print(f"✅ Voter {matric_number} face registered successfully!")
            
            # Also save the face image for reference
            voter_encodings_path = os.path.join(settings.FACE_DATA_PATH, 'voters')
            face_image_path = os.path.join(voter_encodings_path, f"{matric_number}_face.jpg")
            
            # Extract and save the detected face
            face, _ = face_recognizer.detect_and_align_face(image)
            if face is not None:
                cv2.imwrite(face_image_path, face)
                print(f"✅ Face image saved to: {face_image_path}")
            
            print("\n🎉 Registration complete!")
            print("The voter can now use face verification in the Telegram bot.")
        else:
            print("❌ Failed to register voter face")
        
    except Exception as e:
        print(f"❌ Error registering face: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
