import streamlit as st
import cv2
import numpy as np
import os
import json
import logging
from face_recognition import FaceRecognizer
from datetime import datetime

# Configure logging
logging.basicConfig(
    filename='logs/bot.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class FaceCaptureApp:
    def __init__(self):
        self.face_recognizer = FaceRecognizer('data/face_data')
        self.base_dir = os.path.abspath(os.path.dirname(__file__))
        if 'capture_complete' not in st.session_state:
            st.session_state.capture_complete = False
        if 'captured_image' not in st.session_state:
            st.session_state.captured_image = None
        if 'matric' not in st.session_state:
            st.session_state.matric = None

    def load_session(self, session_id):
        """Load session data from file"""
        session_file = os.path.join(self.base_dir, "temp", f"session_{session_id}.json")
        try:
            if not os.path.exists(session_file):
                logger.error(f"Session file not found: {session_file}")
                return None
            with open(session_file, 'r') as f:
                session_data = json.load(f)
            logger.info(f"Loaded session {session_id} from {session_file}")
            return session_data
        except Exception as e:
            logger.error(f"Error loading session {session_id}: {e}")
            return None

    def save_session_result(self, session_id, result):
        """Save verification result to session file"""
        session_file = os.path.join(self.base_dir, "temp", f"session_{session_id}.json")
        try:
            session_data = self.load_session(session_id) or {}
            session_data.update({
                'status': 'completed',
                'result': result,
                'timestamp': datetime.now().isoformat()
            })
            with open(session_file, 'w') as f:
                json.dump(session_data, f)
            logger.info(f"Saved result for session {session_id}")
        except Exception as e:
            logger.error(f"Error saving session result {session_id}: {e}")

    def run(self):
        """Main Streamlit app"""
        st.set_page_config(page_title="E-Voting Face Verification", layout="centered")
        st.title("🗳️ E-Voting Face Verification")
        
        query_params = st.query_params
        session_id = query_params.get("session_id", None)
        if not session_id:
            st.error("❌ No session ID provided. Please access this page via the Telegram bot.")
            logger.error("No session_id in URL")
            return

        session_data = self.load_session(session_id)
        if not session_data:
            st.error("❌ Session not found. Please request a new verification link from the Telegram bot.")
            logger.error(f"Session {session_id} not found")
            return

        session_type = session_data.get('type')
        user_id = session_data.get('user_id')
        st.markdown(f"**Session ID:** `{session_id}`")
        st.markdown(f"**Verification Type**: {'Admin' if session_type == 'admin' else 'Voter' if session_type == 'vote' else 'Voter Registration'}")

        if session_type == 'voter_registration':
            matric = st.text_input("Enter voter matric number (e.g., STU008)", key="matric_input")
            if matric:
                st.session_state.matric = matric
            else:
                st.warning("Please enter a matric number to proceed.")
                return

        if st.session_state.capture_complete:
            st.image(st.session_state.captured_image, caption="Preview of Captured Face", use_container_width=True)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ CONTINUE WITH THIS IMAGE", key="confirm"):
                    save_path = os.path.join("temp", f"{session_id}_face.jpg")
                    try:
                        cv2.imwrite(save_path, cv2.cvtColor(st.session_state.captured_image, cv2.COLOR_RGB2BGR))
                        # Perform face verification
                        if session_type == 'admin':
                            verified, identity = self.face_recognizer.verify_admin_face(st.session_state.captured_image, user_id)
                            result = {'verified': verified, 'matric': None}
                        elif session_type == 'vote':
                            verified, identity = self.face_recognizer.verify_voter_face(st.session_state.captured_image)
                            result = {'verified': verified, 'matric': identity}
                        else:  # voter_registration
                            matric = st.session_state.matric
                            if not matric:
                                st.error("❌ Matric number required for voter registration.")
                                logger.error(f"No matric provided for session {session_id}")
                                return
                            verified = self.face_recognizer.register_voter_face(st.session_state.captured_image, matric)
                            result = {'verified': verified, 'matric': matric}
                        self.save_session_result(session_id, result)
                        if verified:
                            st.success(f"✅ Verification successful! Image saved to {save_path}. Return to Telegram and type {'/check_admin' if session_type == 'admin' else '/check_vote' if session_type == 'vote' else '/check_voter_registration'}.")
                            logger.info(f"Verification successful for session {session_id} ({session_type})")
                        else:
                            st.error("❌ Verification failed. Please try again.")
                            logger.warning(f"Verification failed for session {session_id} ({session_type})")
                            st.session_state.capture_complete = False
                            st.session_state.captured_image = None
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Failed to process image: {e}")
                        logger.error(f"Error processing image for session {session_id}: {e}")
                        st.session_state.capture_complete = False
                        st.session_state.captured_image = None
                        st.rerun()
            with col2:
                if st.button("🔄 RETAKE IMAGE", key="retake"):
                    st.session_state.capture_complete = False
                    st.session_state.captured_image = None
                    st.rerun()
        else:
            run = st.checkbox("Turn on camera")
            FRAME_WINDOW = st.empty()
            if run:
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    st.error("❌ Cannot access webcam. Please ensure it is connected and try again.")
                    logger.error("Webcam not accessible")
                    return
                st.markdown("### Live Camera Feed")
                capture_btn = st.button("📸 Capture Image", key="capture_button")
                while run:
                    ret, frame = cap.read()
                    if not ret:
                        st.error("❌ Could not access webcam.")
                        logger.error("Failed to capture video frame")
                        break
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    FRAME_WINDOW.image(frame, channels="RGB", use_container_width=True)
                    if capture_btn:
                        st.session_state.captured_image = frame
                        st.session_state.capture_complete = True
                        cap.release()
                        break
                cap.release()
            else:
                st.info("✔️ Click the checkbox to turn on the camera.")

if __name__ == "__main__":
    app = FaceCaptureApp()
    app.run()
