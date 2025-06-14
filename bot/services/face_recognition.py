import os
import logging
import numpy as np
import cv2
from mtcnn.mtcnn import MTCNN
from keras_facenet import FaceNet
from scipy import spatial
import dlib
from django.conf import settings

logger = logging.getLogger(__name__)

class FaceRecognizer:
    def __init__(self):
        logger.info("Initializing MTCNN, FaceNet, and Dlib")
        self.detector = MTCNN()
        self.facenet = FaceNet()
        
        # Load dlib shape predictor
        shape_predictor_path = os.path.join(settings.FACE_MODELS_PATH, 'dlib', 'shape_predictor_68_face_landmarks.dat')
        if not os.path.exists(shape_predictor_path):
            logger.error(f"Shape predictor file not found at {shape_predictor_path}")
            raise FileNotFoundError(f"Shape predictor file not found at {shape_predictor_path}")
        
        self.predictor = dlib.shape_predictor(shape_predictor_path)
        self.face_data_path = settings.FACE_DATA_PATH
        self.voter_encodings_path = os.path.join(self.face_data_path, 'voters')
        self.admin_encodings_path = os.path.join(self.face_data_path, 'admins')
        self.voter_encodings = {}
        self.admin_encodings = {}
        self.load_encodings()

    def detect_and_align_face(self, img):
        """Detect and align face from a NumPy array."""
        try:
            if not isinstance(img, np.ndarray):
                logger.error("Input must be a NumPy array")
                return None, None
            results = self.detector.detect_faces(img)
            if not results:
                logger.warning("No face detected")
                return None, None
            x, y, w, h = results[0]['box']
            face = img[y:y+h, x:x+w]
            face = cv2.resize(face, (160, 160))
            return face, (x, y, w, h)
        except Exception as e:
            logger.error(f"Face detection failed: {e}")
            return None, None

    def generate_embedding(self, face):
        """Generate FaceNet embedding from a face image."""
        try:
            face = np.expand_dims(face, axis=0)
            embedding = self.facenet.embeddings(face)[0]
            return embedding
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def detect_blinks(self, frame, landmarks):
        """Detect blinks for liveness check."""
        try:
            left_eye = [(landmarks.part(i).x, landmarks.part(i).y) for i in range(36, 42)]
            right_eye = [(landmarks.part(i).x, landmarks.part(i).y) for i in range(42, 48)]
            def eye_aspect_ratio(eye):
                A = np.linalg.norm(np.array(eye[1]) - np.array(eye[5]))
                B = np.linalg.norm(np.array(eye[2]) - np.array(eye[4]))
                C = np.linalg.norm(np.array(eye[0]) - np.array(eye[3]))
                return (A + B) / (2.0 * C)
            ear = (eye_aspect_ratio(left_eye) + eye_aspect_ratio(right_eye)) / 2.0
            return ear < 0.2
        except Exception as e:
            logger.error(f"Blink detection failed: {e}")
            return False

    def load_encodings(self):
        """Load stored face encodings."""
        try:
            for filename in os.listdir(self.voter_encodings_path):
                if filename.endswith('.npy'):
                    identifier = filename.split('.')[0]
                    self.voter_encodings[identifier] = np.load(os.path.join(self.voter_encodings_path, filename))
            logger.info(f"Loaded {len(self.voter_encodings)} voters encodings")
            
            for filename in os.listdir(self.admin_encodings_path):
                if filename.endswith('.npy'):
                    identifier = filename.split('.')[0]
                    self.admin_encodings[identifier] = np.load(os.path.join(self.admin_encodings_path, filename))
            logger.info(f"Loaded {len(self.admin_encodings)} admins encodings")
        except Exception as e:
            logger.error(f"Error loading encodings: {e}")

    def verify_voter_face(self, img):
        """Verify voter face from a NumPy array."""
        face, _ = self.detect_and_align_face(img)
        if face is None:
            return False, None
        embedding = self.generate_embedding(face)
        if embedding is None:
            return False, None
        min_dist = float('inf')
        identity = None
        for voter_id, voter_embedding in self.voter_encodings.items():
            dist = spatial.distance.cosine(embedding, voter_embedding)
            if dist < min_dist and dist < 0.4:
                min_dist = dist
                identity = voter_id
        if identity:
            logger.info(f"Voter {identity} verified with distance {min_dist}")
            return True, identity
        logger.warning("No matching voter found")
        return False, None

    def verify_admin_face(self, img, user_id):
        """Verify admin face from a NumPy array."""
        face, _ = self.detect_and_align_face(img)
        if face is None:
            return False, None
        embedding = self.generate_embedding(face)
        if embedding is None:
            return False, None
        admin_embedding = self.admin_encodings.get(str(user_id))
        if admin_embedding is None:
            logger.warning(f"No encoding found for admin {user_id}")
            return False, None
        dist = spatial.distance.cosine(embedding, admin_embedding)
        if dist < 0.4:
            logger.info(f"Admin {user_id} verified with distance {dist}")
            return True, user_id
        logger.warning(f"Admin {user_id} verification failed with distance {dist}")
        return False, None

    def register_voter_face(self, img, matric):
        """Register voter face from a NumPy array or file path."""
        try:
            if isinstance(img, str):
                img_array = cv2.imread(img)
                if img_array is None:
                    logger.error(f"Failed to read image {img}")
                    return False
            else:
                img_array = img
            face, _ = self.detect_and_align_face(img_array)
            if face is None:
                return False
            embedding = self.generate_embedding(face)
            if embedding is None:
                return False
            np.save(os.path.join(self.voter_encodings_path, f"{matric}.npy"), embedding)
            self.voter_encodings[matric] = embedding
            logger.info(f"Registered voter {matric} face")
            return True
        except Exception as e:
            logger.error(f"Error registering voter {matric}: {e}")
            return False
