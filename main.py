import logging
import os
import json
import hashlib
import threading
import time
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from datetime import datetime
from database import Database
from face_recognition import FaceRecognizer
import subprocess
import asyncio

# Set up logging
logging.basicConfig(
    filename='logs/bot.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Define states for ConversationHandler
(
    ADMIN_AUTH,
    ADMIN_ACTION,
    ADD_ADMIN,
    REMOVE_ADMIN,
    CREATE_ELECTION,
    ADD_CANDIDATE,
    ADD_CANDIDATE_PHOTO,
    VOTER_AUTH,
    VOTER_VOTE,
    VOTER_REPORT,
    ADD_VOTER,
    WAITING_FACE_CAPTURE,
    VIEW_CANDIDATES,
    VIEW_REPORTS,
) = range(14)

# Global variables for Streamlit communication
streamlit_process = None

class StreamlitManager:
    def __init__(self):
        self.sessions = {}
        self.streamlit_url = "http://localhost:8501"
        self.base_dir = os.path.abspath(os.path.dirname(__file__))
        
    def start_streamlit(self):
        """Start Streamlit app in background"""
        global streamlit_process
        try:
            streamlit_process = subprocess.Popen([
                "streamlit", "run", "streamlit_face_capture.py", 
                "--server.port=8501", "--server.headless=true"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.base_dir)
            time.sleep(15)
            if streamlit_process.poll() is not None:
                stdout, stderr = streamlit_process.communicate()
                logger.error(f"Streamlit failed to start: {stderr.decode()}")
                raise RuntimeError("Streamlit process terminated unexpectedly")
            logger.info("Streamlit app started on port 8501")
        except Exception as e:
            logger.error(f"Failed to start Streamlit: {e}")
            raise
    
    def create_session(self, user_id, session_type, election_id=None):
        """Create a new face capture session"""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            'user_id': user_id,
            'type': session_type,
            'election_id': election_id,
            'status': 'pending',
            'result': None,
            'timestamp': datetime.now().isoformat()
        }
        
        session_file = os.path.join(self.base_dir, "temp", f"session_{session_id}.json")
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        try:
            with open(session_file, 'w') as f:
                json.dump(self.sessions[session_id], f)
            logger.info(f"Created session {session_id} for user {user_id} ({session_type}) at {session_file}")
            return session_id
        except Exception as e:
            logger.error(f"Failed to create session {session_id}: {e}")
            raise
    
    def get_session_result(self, session_id):
        """Get the result of a face capture session"""
        session_file = os.path.join(self.base_dir, "temp", f"session_{session_id}.json")
        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
            return session_data.get('status'), session_data.get('result')
        except Exception as e:
            logger.error(f"Error reading session {session_id} from {session_file}: {e}")
            return 'pending', None
    
    def cleanup_session(self, session_id):
        """Clean up session files"""
        session_file = os.path.join(self.base_dir, "temp", f"session_{session_id}.json")
        try:
            if os.path.exists(session_file):
                os.remove(session_file)
            if session_id in self.sessions:
                del self.sessions[session_id]
            logger.info(f"Cleaned up session {session_id}")
        except Exception as e:
            logger.error(f"Error cleaning session {session_id}: {e}")

# Initialize Streamlit manager
streamlit_manager = StreamlitManager()

def hash_vote(matric, candidate_id, election_id, timestamp):
    """Generate cryptographic hash for vote"""
    try:
        vote_string = f"{matric}:{candidate_id}:{election_id}:{timestamp}"
        return hashlib.sha256(vote_string.encode()).hexdigest()
    except Exception as e:
        logger.error(f"Error hashing vote: {e}")
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} started the bot")
    await update.message.reply_text(
        f"Hello {user.first_name}! Welcome to the E-Voting Bot.\n"
        "Commands:\n"
        "/vote - Cast your vote\n"
        "/help - View commands\n"
        "/view_candidate - View candidates\n"
        "/results - View election results\n"
        "/report - Report an issue\n"
        "/admin - Admin functions"
    )
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Available Commands:\n"
        "/vote - Cast your vote\n"
        "/help - View commands\n"
        "/view_candidate - View candidates\n"
        "/results - View election results\n"
        "/report - Report an issue\n"
        "/admin - Admin functions"
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} requested admin access")
    try:
        session_id = streamlit_manager.create_session(
            user_id=update.effective_user.id,
            session_type='admin'
        )
        streamlit_url = f"{streamlit_manager.streamlit_url}?session_id={session_id}"
        await update.message.reply_text(
            f"🔒 Admin Verification Required\n\n"
            f"Please click the link below to complete face verification:\n"
            f"{streamlit_url}\n\n"
            f"This link will expire in 10 minutes.\n"
            f"After completing verification, return here and type /check_admin"
        )
        context.user_data['admin_session_id'] = session_id
        return WAITING_FACE_CAPTURE
    except Exception as e:
        logger.error(f"Admin session creation failed for user {update.effective_user.id}: {e}")
        await update.message.reply_text("❌ Error initiating admin verification. Please try again later.")
        return ConversationHandler.END

async def check_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session_id = context.user_data.get('admin_session_id')
    if not session_id:
        await update.message.reply_text("No verification session found. Please use /admin to start.")
        return ConversationHandler.END
    status, result = streamlit_manager.get_session_result(session_id)
    if status == 'completed' and result and result.get('verified'):
        logger.info(f"Admin {update.effective_user.id} verified successfully via Streamlit")
        context.user_data['is_admin'] = True  # Store admin status
        streamlit_manager.cleanup_session(session_id)
        keyboard = [
            [InlineKeyboardButton("Create Election", callback_data='create_election')],
            [InlineKeyboardButton("Add Candidate", callback_data='add_candidate')],
            [InlineKeyboardButton("View Candidates", callback_data='view_candidates')],
            [InlineKeyboardButton("View Reports", callback_data='view_reports')],
            [InlineKeyboardButton("Add Admin", callback_data='add_admin')],
            [InlineKeyboardButton("Remove Admin", callback_data='remove_admin')],
            [InlineKeyboardButton("Add Voter", callback_data='add_voter')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("✅ Admin verified! Choose an action:", reply_markup=reply_markup)
        return ADMIN_ACTION
    elif status == 'completed' and result and not result.get('verified'):
        logger.warning(f"Admin verification failed for user {update.effective_user.id}")
        streamlit_manager.cleanup_session(session_id)
        await update.message.reply_text("❌ Admin verification failed. Access denied.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("⏳ Verification still in progress. Please complete the face capture and try again.")
        return WAITING_FACE_CAPTURE

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    if action == 'create_election':
        await query.message.reply_text("Enter election details (title, start_time, end_time) format: Title, YYYY-MM-DD HH:MM, YYYY-MM-DD HH:MM")
        return CREATE_ELECTION
    elif action == 'add_candidate':
        await query.message.reply_text("Enter candidate details (name, position, election_id)")
        context.user_data['candidate_data'] = {}
        return ADD_CANDIDATE
    elif action == 'view_candidates':
        db = context.bot_data['database']
        elections = db.get_active_elections()
        if not elections:
            await query.message.reply_text("❌ No active elections available.")
            return ADMIN_ACTION
        keyboard = [
            [InlineKeyboardButton(election[1], callback_data=f"view_cand_{election[0]}")]
            for election in elections
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Select an election to view candidates:", reply_markup=reply_markup)
        return VIEW_CANDIDATES
    elif action == 'view_reports':
        db = context.bot_data['database']
        reports = db.get_reports()
        if not reports:
            await query.message.reply_text("❌ No reports available.")
            return ADMIN_ACTION
        report_text = "📋 Voter Reports:\n"
        for report_id, voter_id, issue, timestamp in reports:
            report_text += f"Report ID: {report_id}\nVoter ID: {voter_id}\nIssue: {issue}\nTime: {timestamp}\n\n"
        await query.message.reply_text(report_text)
        return ADMIN_ACTION
    elif action == 'add_admin':
        await query.message.reply_text("Enter new admin Telegram ID")
        return ADD_ADMIN
    elif action == 'remove_admin':
        await query.message.reply_text("Enter admin Telegram ID to remove")
        return REMOVE_ADMIN
    elif action == 'add_voter':
        await query.message.reply_text("Enter voter matric number")
        return ADD_VOTER

async def create_election(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        input_text = update.message.text
        title, start_time, end_time = [x.strip() for x in input_text.split(',')]
        start_time = datetime.strptime(start_time, '%Y-%m-%d %H:%M')
        end_time = datetime.strptime(end_time, '%Y-%m-%d %H:%M')
        if end_time <= start_time:
            raise ValueError("End time must be after start time")
        db = context.bot_data['database']
        election_id = db.create_election(title, start_time, end_time)
        await update.message.reply_text(f"✅ Election '{title}' created with ID {election_id}")
        return ADMIN_ACTION
    except Exception as e:
        logger.error(f"Error creating election: {str(e)}")
        await update.message.reply_text(f"❌ Invalid format: {str(e)}. Use: Title, YYYY-MM-DD HH:MM, YYYY-MM-DD HH:MM")
        return CREATE_ELECTION

async def add_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name, position, election_id = [x.strip() for x in update.message.text.split(',')]
        context.user_data['candidate_data'] = {
            'name': name,
            'position': position,
            'election_id': election_id
        }
        await update.message.reply_text("Please upload a photo of the candidate (JPEG/PNG).")
        return ADD_CANDIDATE_PHOTO
    except Exception as e:
        logger.error(f"Error parsing candidate details: {str(e)}")
        await update.message.reply_text(f"❌ Invalid format: {str(e)}. Use: Name, Position, Election ID")
        return ADD_CANDIDATE

async def add_candidate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.photo:
            await update.message.reply_text("❌ Please upload a photo (JPEG/PNG).")
            return ADD_CANDIDATE_PHOTO
        photo = update.message.photo[-1]
        file = await photo.get_file()
        candidate_data = context.user_data.get('candidate_data')
        if not candidate_data:
            await update.message.reply_text("❌ Candidate data not found. Please start again with /add_candidate.")
            return ADD_CANDIDATE
        db = context.bot_data['database']
        candidate_id = str(uuid.uuid4())
        image_path = os.path.join('data', 'candidate_images', f"{candidate_id}.jpg")
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        await file.download_to_drive(image_path)
        db.add_candidate(
            candidate_data['name'],
            candidate_data['position'],
            candidate_data['election_id'],
            image_path
        )
        await update.message.reply_text(f"✅ Candidate {candidate_data['name']} added for {candidate_data['position']} with photo.")
        del context.user_data['candidate_data']
        return ADMIN_ACTION
    except Exception as e:
        logger.error(f"Error adding candidate photo: {str(e)}")
        await update.message.reply_text(f"❌ Error uploading photo: {str(e)}. Please try again.")
        return ADD_CANDIDATE_PHOTO

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = update.message.text.strip()
        db = context.bot_data['database']
        db.add_admin_id(admin_id)
        await update.message.reply_text(f"✅ Admin {admin_id} added. They can now use /admin to register their face.")
        return ADMIN_ACTION
    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        await update.message.reply_text("❌ Invalid Telegram ID")
        return ADD_ADMIN

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = update.message.text.strip()
        db = context.bot_data['database']
        db.remove_admin_id(admin_id)
        await update.message.reply_text(f"✅ Admin {admin_id} removed")
        return ADMIN_ACTION
    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        await update.message.reply_text("❌ Invalid Telegram ID")
        return REMOVE_ADMIN

async def voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db = context.bot_data['database']
    is_admin = db.is_admin(user_id)
    logger.info(f"User {user_id} requested /voters, is_admin={is_admin}")
    if is_admin or context.user_data.get('is_admin', False):
        logger.info(f"Admin {user_id} authorized to add voter")
        try:
            session_id = streamlit_manager.create_session(
                user_id=user_id,
                session_type='voter_registration'
            )
            streamlit_url = f"{streamlit_manager.streamlit_url}?session_id={session_id}"
            await update.message.reply_text(
                f"📸 Voter Registration\n\n"
                f"Please click the link below to capture voter face:\n"
                f"{streamlit_url}\n\n"
                f"This link will expire in 10 minutes.\n"
                f"After capturing, return here and type /check_voter_registration"
            )
            context.user_data['voter_session_id'] = session_id
            return WAITING_FACE_CAPTURE
        except Exception as e:
            logger.error(f"Voter registration session failed for user {user_id}: {e}")
            await update.message.reply_text("❌ Error initiating voter registration. Please try again later.")
            return ConversationHandler.END
    else:
        logger.warning(f"Non-admin {user_id} attempted to add voter")
        await update.message.reply_text("❌ Only admins can add voters.")
        return ConversationHandler.END

async def check_voter_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session_id = context.user_data.get('voter_session_id')
    if not session_id:
        await update.message.reply_text("No registration session found. Please use /voters to start.")
        return ConversationHandler.END
    status, result = streamlit_manager.get_session_result(session_id)
    if status == 'completed' and result and result.get('verified'):
        matric = result.get('matric')
        logger.info(f"Voter {matric} registered successfully via Streamlit")
        db = context.bot_data['database']
        db.add_voter(matric)
        streamlit_manager.cleanup_session(session_id)
        await update.message.reply_text(f"✅ Voter {matric} registered successfully")
        return ADMIN_ACTION
    elif status == 'completed' and result and not result.get('verified'):
        logger.warning(f"Voter registration failed")
        streamlit_manager.cleanup_session(session_id)
        await update.message.reply_text("❌ Voter registration failed. Please try again.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("⏳ Registration still in progress. Please complete the face capture and try again.")
        return WAITING_FACE_CAPTURE

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} requested to vote")
    try:
        db = context.bot_data['database']
        elections = db.get_active_elections()
        if not elections:
            await update.message.reply_text("❌ No active elections available.")
            return ConversationHandler.END
        session_id = streamlit_manager.create_session(
            user_id=update.effective_user.id,
            session_type='vote'
        )
        streamlit_url = f"{streamlit_manager.streamlit_url}?session_id={session_id}"
        await update.message.reply_text(
            f"🗳️ Voter Verification Required\n\n"
            f"Please click the link below to complete face verification:\n"
            f"{streamlit_url}\n\n"
            f"This link will expire in 10 minutes.\n"
            f"After completing verification, return here and type /check_vote"
        )
        context.user_data['vote_session_id'] = session_id
        return WAITING_FACE_CAPTURE
    except Exception as e:
        logger.error(f"Voter session creation failed for user {update.effective_user.id}: {e}")
        await update.message.reply_text("❌ Error initiating voter verification. Please try again later.")
        return ConversationHandler.END

async def check_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session_id = context.user_data.get('vote_session_id')
    if not session_id:
        await update.message.reply_text("No verification session found. Please use /vote to start.")
        return ConversationHandler.END
    status, result = streamlit_manager.get_session_result(session_id)
    if status == 'completed' and result and result.get('verified'):
        matric = result.get('matric')
        logger.info(f"Voter {matric} verified successfully via Streamlit")
        streamlit_manager.cleanup_session(session_id)
        db = context.bot_data['database']
        if not db.voter_exists(matric):
            logger.warning(f"Voter {matric} not in database")
            await update.message.reply_text("❌ Voter not registered in database.")
            return ConversationHandler.END
        context.user_data['matric'] = matric
        elections = db.get_active_elections()
        keyboard = [
            [InlineKeyboardButton(election[1], callback_data=str(election[0]))]
            for election in elections
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("✅ Voter verified! Select an election:", reply_markup=reply_markup)
        return VOTER_VOTE
    elif status == 'completed' and result and not result.get('verified'):
        logger.warning(f"Voter verification failed for user {update.effective_user.id}")
        streamlit_manager.cleanup_session(session_id)
        await update.message.reply_text("❌ Voter verification failed.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("⏳ Verification still in progress. Please complete the face capture and try again.")
        return WAITING_FACE_CAPTURE

async def voter_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    election_id = query.data
    context.user_data['election_id'] = election_id
    db = context.bot_data['database']
    candidates = db.get_candidates(election_id)
    if not candidates:
        logger.info(f"No candidates for election {election_id}")
        await query.message.reply_text("❌ No candidates available.")
        return ConversationHandler.END
    positions = {}
    for cid, name, pos, _ in candidates:
        if pos not in positions:
            positions[pos] = []
        positions[pos].append((cid, name))
    context.user_data['vote_stage'] = list(positions.keys())
    context.user_data['vote_data'] = {}
    context.user_data['candidates_by_position'] = positions
    await send_position(query, context)
    return VOTER_VOTE

async def send_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stages = context.user_data.get('vote_stage', [])
    if not stages:
        await submit_vote(update, context)
        return
    pos = stages[0]
    context.user_data['current_position'] = pos
    candidates = context.user_data['candidates_by_position'][pos]
    buttons = [[InlineKeyboardButton(name, callback_data=cid)] for cid, name in candidates]
    await update.message.reply_text(f"Vote for: {pos}", reply_markup=InlineKeyboardMarkup(buttons))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    candidate_id = query.data
    pos = context.user_data.get('current_position')
    context.user_data['vote_data'][pos] = candidate_id
    context.user_data['vote_stage'].pop(0)
    await send_position(query, context)

async def submit_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data['vote_data']
    election_id = context.user_data['election_id']
    matric = context.user_data['matric']
    db = context.bot_data['database']
    try:
        for pos, candidate_id in data.items():
            timestamp = datetime.now().isoformat()
            vote_hash = hash_vote(matric, candidate_id, election_id, timestamp)
            db.cast_vote(matric, candidate_id, election_id, vote_hash, timestamp)
        await query.message.reply_text(
            f"✅ Your votes have been submitted successfully!\n"
            f"Vote hash: {vote_hash[:16]}...\n"
            f"Keep this hash for verification purposes."
        )
    except Exception as e:
        logger.error(f"Error casting vote for {matric}: {e}")
        await query.message.reply_text("❌ Error casting vote. You may have already voted.")
    return ConversationHandler.END

async def view_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data['database']
    elections = db.get_active_elections()
    if not elections:
        await update.message.reply_text("❌ No active elections available.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton(election[1], callback_data=f"view_cand_{election[0]}")]
        for election in elections
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select an election to view candidates:", reply_markup=reply_markup)
    return VIEW_CANDIDATES

async def view_candidates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    election_id = query.data.replace("view_cand_", "")
    db = context.bot_data['database']
    candidates = db.get_candidates(election_id)
    if not candidates:
        await query.message.reply_text("❌ No candidates available for this election.")
        return ADMIN_ACTION if context.user_data.get('is_admin') else ConversationHandler.END
    for candidate_id, name, position, image_path in candidates:
        message = f"Candidate: {name}\nPosition: {position}"
        try:
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as photo:
                    await query.message.reply_photo(
                        photo=InputFile(photo),
                        caption=message
                    )
            else:
                await query.message.reply_text(message)
        except Exception as e:
            logger.error(f"Error sending candidate {name} image: {e}")
            await query.message.reply_text(f"{message}\n⚠️ Image not available.")
    return ADMIN_ACTION if context.user_data.get('is_admin') else ConversationHandler.END

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Describe the issue you want to report:")
    return VOTER_REPORT

async def submit_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    issue = update.message.text
    user_id = update.effective_user.id
    db = context.bot_data['database']
    db.store_report(user_id, issue)
    logger.info(f"Report submitted by user {user_id}: {issue}")
    await update.message.reply_text("✅ Report submitted. Thank you!")
    return ConversationHandler.END

async def results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data['database']
    elections = db.get_all_elections()
    if not elections:
        await update.message.reply_text("❌ No elections found.")
        return
    for election in elections:
        election_id, title, _, end_time = election
        end_time_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        if datetime.now() >= end_time_dt:
            vote_counts = db.get_vote_counts(election_id)
            if vote_counts:
                results_text = "\n".join([f"• {name} ({position}): {count} votes" for _, name, position, count in vote_counts])
                await update.message.reply_text(f"📊 Results for {title}:\n{results_text}")
            else:
                await update.message.reply_text(f"📊 No votes for {title} yet.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"User {update.effective_user.id} cancelled operation")
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and (update.message or update.callback_query):
        chat = update.message.chat if update.message else update.callback_query.message.chat
        await chat.send_message("❌ An unexpected error occurred. Please try again or contact support.")

def cleanup_old_sessions():
    temp_dir = os.path.join(streamlit_manager.base_dir, "temp")
    if not os.path.exists(temp_dir):
        return
    current_time = datetime.now()
    for filename in os.listdir(temp_dir):
        if filename.startswith("session_"):
            file_path = os.path.join(temp_dir, filename)
            try:
                with open(file_path, 'r') as f:
                    session_data = json.load(f)
                session_time = datetime.fromisoformat(session_data['timestamp'].replace('Z', '+00:00'))
                if (current_time - session_time).total_seconds() > 600:
                    os.remove(file_path)
                    logger.info(f"Cleaned up old session: {filename}")
            except Exception as e:
                logger.error(f"Error cleaning session {filename}: {e}")

def main():
    token = "7302819268:AAGAiq--bcMfZVkIP79C9y54HkUZKfvh1FE"
    application = Application.builder().token(token).build()
    db = Database('data/voting.db')
    face_recognizer = FaceRecognizer('data/face_data')
    application.bot_data['database'] = db
    application.bot_data['face_recognizer'] = face_recognizer
    streamlit_manager.start_streamlit()
    cleanup_thread = threading.Thread(target=lambda: [time.sleep(60), cleanup_old_sessions()], daemon=True)
    cleanup_thread.start()
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('help', help_command),
            CommandHandler('admin', admin),
            CommandHandler('vote', vote),
            CommandHandler('voters', voters),
            CommandHandler('report', report),
            CommandHandler('view_candidate', view_candidate),
        ],
        states={
            WAITING_FACE_CAPTURE: [
                CommandHandler('check_admin', check_admin),
                CommandHandler('check_vote', check_vote),
                CommandHandler('check_voter_registration', check_voter_registration),
            ],
            ADMIN_ACTION: [CallbackQueryHandler(admin_action)],
            ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin)],
            REMOVE_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_admin)],
            CREATE_ELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_election)],
            ADD_CANDIDATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_candidate)],
            ADD_CANDIDATE_PHOTO: [MessageHandler(filters.PHOTO, add_candidate_photo)],
            VOTER_VOTE: [CallbackQueryHandler(voter_vote), CallbackQueryHandler(button_handler)],
            VOTER_REPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, submit_report)],
            ADD_VOTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, voters)],
            VIEW_CANDIDATES: [CallbackQueryHandler(view_candidates_callback)],
            VIEW_REPORTS: [CallbackQueryHandler(admin_action)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        conversation_timeout=35
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('results', results))
    application.add_error_handler(error_handler)
    try:
        logger.info("Bot started")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(application.run_polling())
    except Exception as e:
        logger.error(f"Bot stopped with error: {e}")
    finally:
        if streamlit_process:
            streamlit_process.terminate()
            streamlit_process.wait()
            logger.info("Streamlit process terminated")
        if 'db' in locals():
            db.__del__()
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.close()
        logger.info("Application shutdown complete")

if __name__ == "__main__":
    main()
