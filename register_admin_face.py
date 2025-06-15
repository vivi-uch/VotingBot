#!/usr/bin/env python
"""
Script to register admin face encodings
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
from bot.models import Admin
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
        cv2.imshow('Admin Face Registration - Press SPACE to capture, ESC to cancel', frame)
        
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
    print("👤 Admin Face Registration")
    print("=" * 30)
    
    # Get admin Telegram ID
    telegram_id = input("Enter admin Telegram ID: ").strip()
    
    if not telegram_id:
        print("❌ Telegram ID cannot be empty")
        return
    
    # Check if admin exists in database
    try:
        if not Admin.objects.filter(telegram_id=telegram_id).exists():
            print(f"❌ Admin {telegram_id} not found in database")
            create = input("Do you want to create this admin? (y/n): ").lower()
            if create == 'y':
                Admin.objects.create(telegram_id=telegram_id)
                print(f"✅ Admin {telegram_id} created")
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
        
        # Detect face
        face, bbox = face_recognizer.detect_and_align_face(image)
        if face is None:
            print("❌ No face detected in image")
            return
        
        print("✅ Face detected")
        
        # Generate embedding
        embedding = face_recognizer.generate_embedding(face)
        if embedding is None:
            print("❌ Failed to generate face embedding")
            return
        
        print("✅ Face embedding generated")
        
        # Save embedding
        admin_encodings_path = os.path.join(settings.FACE_DATA_PATH, 'admins')
        os.makedirs(admin_encodings_path, exist_ok=True)
        
        encoding_file = os.path.join(admin_encodings_path, f"{telegram_id}.npy")
        np.save(encoding_file, embedding)
        
        print(f"✅ Face encoding saved to: {encoding_file}")
        
        # Also save the face image for reference
        face_image_path = os.path.join(admin_encodings_path, f"{telegram_id}_face.jpg")
        cv2.imwrite(face_image_path, face)
        print(f"✅ Face image saved to: {face_image_path}")
        
        print(f"\n🎉 Admin {telegram_id} face registered successfully!")
        print("You can now use face verification in the Telegram bot.")
        
    except Exception as e:
        print(f"❌ Error registering face: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
