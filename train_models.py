import os
import cv2
import numpy as np
from mtcnn.mtcnn import MTCNN
from keras_facenet import FaceNet
import logging

logging.basicConfig(
    filename='logs/bot.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ModelTrainer:
    def __init__(self, training_data_path, output_data_path):
        logger.info("Initializing MTCNN and FaceNet for training")
        self.detector = MTCNN()
        self.facenet = FaceNet()
        self.training_data_path = training_data_path
        self.output_data_path = output_data_path
        self.voters_path = os.path.join(training_data_path, 'voters')
        self.admins_path = os.path.join(training_data_path, 'admins')
        self.voters_output = os.path.join(output_data_path, 'voters')
        self.admins_output = os.path.join(output_data_path, 'admins')
        try:
            os.makedirs(self.voters_output, exist_ok=True)
            os.makedirs(self.admins_output, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating output directories: {e}")
            raise

    def detect_and_align_face(self, img):
        """Detect and align face from a NumPy array."""
        try:
            results = self.detector.detect_faces(img)
            if not results:
                logger.warning("No face detected")
                return None
            x, y, w, h = results[0]['box']
            face = img[y:y+h, x:x+w]
            face = cv2.resize(face, (160, 160))
            return face
        except Exception as e:
            logger.error(f"Face detection failed: {e}")
            return None

    def generate_embedding(self, face):
        """Generate 128D FaceNet embedding from a face image."""
        try:
            face = np.expand_dims(face, axis=0)
            embedding = self.facenet.embeddings(face)[0]
            return embedding
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def process_images(self, input_dir, output_dir):
        """Process images in input_dir, saving embeddings to output_dir."""
        try:
            if not os.path.exists(input_dir):
                logger.warning(f"Input directory {input_dir} does not exist")
                return
            for filename in os.listdir(input_dir):
                if filename.endswith(('.jpg', '.png')):
                    identifier = filename.split('.')[0]
                    img_path = os.path.join(input_dir, filename)
                    img = cv2.imread(img_path)
                    if img is None:
                        logger.warning(f"Failed to load image: {img_path}")
                        continue
                    face = self.detect_and_align_face(img)
                    if face is None:
                        logger.warning(f"No face detected in: {img_path}")
                        continue
                    embedding = self.generate_embedding(face)
                    if embedding is None:
                        continue
                    np.save(os.path.join(output_dir, f"{identifier}.npy"), embedding)
                    logger.info(f"Saved embedding for {identifier}")
            logger.warning("Note: Static images lack liveness checks. Use live capture for secure registration.")
        except Exception as e:
            logger.error(f"Error processing images in {input_dir}: {e}")

    def train(self):
        """Process voter and admin images to generate embeddings."""
        logger.info("Starting training process")
        self.process_images(self.voters_path, self.voters_output)
        self.process_images(self.admins_path, self.admins_output)
        logger.info("Training completed")

if __name__ == "__main__":
    trainer = ModelTrainer(
        training_data_path='models/training_data',
        output_data_path='data/face_data'
    )
    trainer.train()
