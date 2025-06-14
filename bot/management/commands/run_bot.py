import os
import logging
import asyncio
import threading
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
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
from bot.models import Voter, Admin, Election, Candidate, Vote, Report, VerificationSession
from bot.services.face_recognition import FaceRecognizer

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

class Command(BaseCommand):
    help = 'Run the Telegram bot for e-voting'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.face_recognizer = FaceRecognizer()
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))
        
        # Start the bot
        asyncio.run(self.run_bot())
    
    async def run_bot(self):
        """Run the bot."""
        # Create the Application
        application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
        
        # Add handlers
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('start', self.start),
                CommandHandler('help', self.help_command),
                CommandHandler('admin', self.admin),
                CommandHandler('vote', self.vote),
                CommandHandler('voters', self.voters),
                CommandHandler('report', self.report),
                CommandHandler('view_candidate', self.view_candidate),
            ],
            states={
                WAITING_FACE_CAPTURE: [
                    CommandHandler('check_admin', self.check_admin),
                    CommandHandler('check_vote', self.check_vote),
                    CommandHandler('check_voter_registration', self.check_voter_registration),
                ],
                ADMIN_ACTION: [CallbackQueryHandler(self.admin_action)],
                ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_admin)],
                REMOVE_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.remove_admin)],
                CREATE_ELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.create_election)],
                ADD_CANDIDATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_candidate)],
                ADD_CANDIDATE_PHOTO: [MessageHandler(filters.PHOTO, self.add_candidate_photo)],
                VOTER_VOTE: [CallbackQueryHandler(self.voter_vote), CallbackQueryHandler(self.button_handler)],
                VOTER_REPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.submit_report)],
                ADD_VOTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_voter)],
                VIEW_CANDIDATES: [CallbackQueryHandler(self.view_candidates_callback)],
                VIEW_REPORTS: [CallbackQueryHandler(self.admin_action)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
            conversation_timeout=300
        )
        
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler('results', self.results))
        application.add_error_handler(self.error_handler)
        
        # Start cleanup thread
        cleanup_thread = threading.Thread(target=self.cleanup_expired_sessions, daemon=True)
        cleanup_thread.start()
        
        # Start the Bot
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    def cleanup_expired_sessions(self):
        """Clean up expired sessions periodically."""
        while True:
            try:
                # Get expired sessions
                expired_sessions = VerificationSession.objects.filter(
                    status='pending',
                    expires_at__lt=timezone.now()
                )
                
                # Update their status
                count = expired_sessions.update(status='expired')
                if count > 0:
                    logger.info(f"Cleaned up {count} expired sessions")
                
                # Sleep for 60 seconds
                threading.Event().wait(60)
            except Exception as e:
                logger.error(f"Error in cleanup thread: {e}")
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Available Commands:\n"
            "/vote - Cast your vote\n"
            "/help - View commands\n"
            "/view_candidate - View candidates\n"
            "/results - View election results\n"
            "/report - Report an issue\n"
            "/admin - Admin functions"
        )
    
    async def admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"User {update.effective_user.id} requested admin access")
        try:
            # Create verification session
            session = VerificationSession.objects.create(
                user_id=str(update.effective_user.id),
                session_type='admin',
                status='pending'
            )
            
            verification_url = f"{settings.BASE_URL}/verification/capture/{session.id}/"
            
            await update.message.reply_text(
                f"🔒 Admin Verification Required\n\n"
                f"Please click the link below to complete face verification:\n"
                f"{verification_url}\n\n"
                f"This link will expire in 10 minutes.\n"
                f"After completing verification, return here and type /check_admin"
            )
            context.user_data['admin_session_id'] = str(session.id)
            return WAITING_FACE_CAPTURE
        except Exception as e:
            logger.error(f"Admin session creation failed for user {update.effective_user.id}: {e}")
            await update.message.reply_text("❌ Error initiating admin verification. Please try again later.")
            return ConversationHandler.END
    
    async def check_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        session_id = context.user_data.get('admin_session_id')
        if not session_id:
            await update.message.reply_text("No verification session found. Please use /admin to start.")
            return ConversationHandler.END
        
        try:
            session = VerificationSession.objects.get(id=session_id)
            
            if session.status == 'completed' and session.result and session.result.get('verified'):
                logger.info(f"Admin {update.effective_user.id} verified successfully")
                context.user_data['is_admin'] = True  # Store admin status
                
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
            elif session.status == 'completed' and session.result and not session.result.get('verified'):
                logger.warning(f"Admin verification failed for user {update.effective_user.id}")
                await update.message.reply_text("❌ Admin verification failed. Access denied.")
                return ConversationHandler.END
            elif session.status == 'expired':
                logger.warning(f"Admin verification session expired for user {update.effective_user.id}")
                await update.message.reply_text("❌ Verification session expired. Please start again with /admin.")
                return ConversationHandler.END
            else:
                await update.message.reply_text("⏳ Verification still in progress. Please complete the face capture and try again.")
                return WAITING_FACE_CAPTURE
        except VerificationSession.DoesNotExist:
            await update.message.reply_text("❌ Verification session not found. Please start again with /admin.")
            return ConversationHandler.END
    
    async def admin_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        action = query.data
        
        if action == 'create_election':
            await query.message.reply_text("Enter election details (title, start_time, end_time) format: Title, YYYY-MM-DD HH:MM, YYYY-MM-DD HH:MM")
            return CREATE_ELECTION
        elif action == 'add_candidate':
            # Get active elections for candidate addition
            active_elections = Election.objects.filter(status__in=['pending', 'active'])
            if not active_elections:
                await query.message.reply_text("❌ No active elections available to add candidates.")
                return ADMIN_ACTION
            
            keyboard = [
                [InlineKeyboardButton(election.title, callback_data=f"add_cand_{election.id}")]
                for election in active_elections
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Select an election to add a candidate:", reply_markup=reply_markup)
            return ADD_CANDIDATE
        elif action == 'view_candidates':
            active_elections = Election.objects.filter(status__in=['pending', 'active'])
            if not active_elections:
                await query.message.reply_text("❌ No active elections available.")
                return ADMIN_ACTION
            
            keyboard = [
                [InlineKeyboardButton(election.title, callback_data=f"view_cand_{election.id}")]
                for election in active_elections
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Select an election to view candidates:", reply_markup=reply_markup)
            return VIEW_CANDIDATES
        elif action == 'view_reports':
            reports = Report.objects.all().order_by('-timestamp')[:10]  # Get latest 10 reports
            if not reports:
                await query.message.reply_text("❌ No reports available.")
                return ADMIN_ACTION
            
            report_text = "📋 Voter Reports:\n"
            for report in reports:
                report_text += f"Report ID: {report.id}\nVoter ID: {report.voter_id}\nIssue: {report.issue}\nTime: {report.timestamp}\n\n"
            
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
        elif action.startswith('add_cand_'):
            election_id = action.replace('add_cand_', '')
            context.user_data['candidate_election_id'] = election_id
            await query.message.reply_text("Enter candidate details (name, position)")
            return ADD_CANDIDATE
    
    async def create_election(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            input_text = update.message.text
            title, start_time, end_time = [x.strip() for x in input_text.split(',')]
            start_time = timezone.datetime.strptime(start_time, '%Y-%m-%d %H:%M')
            end_time = timezone.datetime.strptime(end_time, '%Y-%m-%d %H:%M')
            
            if end_time <= start_time:
                raise ValueError("End time must be after start time")
            
            # Create election
            election = Election.objects.create(
                title=title,
                start_time=start_time,
                end_time=end_time
            )
            
            await update.message.reply_text(f"✅ Election '{title}' created with ID {election.id}")
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error creating election: {str(e)}")
            await update.message.reply_text(f"❌ Invalid format: {str(e)}. Use: Title, YYYY-MM-DD HH:MM, YYYY-MM-DD HH:MM")
            return CREATE_ELECTION
    
    async def add_candidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if update.callback_query:
                # This is a callback from election selection
                query = update.callback_query
                await query.answer()
                election_id = query.data.replace("add_cand_", "")
                context.user_data['candidate_election_id'] = election_id
                await query.message.reply_text("Enter candidate details (name, position)")
                return ADD_CANDIDATE
            
            # This is text input with candidate details
            name, position = [x.strip() for x in update.message.text.split(',')]
            election_id = context.user_data.get('candidate_election_id')
            
            if not election_id:
                await update.message.reply_text("❌ No election selected. Please start again.")
                return ADMIN_ACTION
            
            context.user_data['candidate_data'] = {
                'name': name,
                'position': position,
                'election_id': election_id
            }
            
            await update.message.reply_text("Please upload a photo of the candidate (JPEG/PNG).")
            return ADD_CANDIDATE_PHOTO
        except Exception as e:
            logger.error(f"Error parsing candidate details: {str(e)}")
            await update.message.reply_text(f"❌ Invalid format: {str(e)}. Use: Name, Position")
            return ADD_CANDIDATE
    
    async def add_candidate_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not update.message.photo:
                await update.message.reply_text("❌ Please upload a photo (JPEG/PNG).")
                return ADD_CANDIDATE_PHOTO
            
            photo = update.message.photo[-1]
            file = await photo.get_file()
            
            candidate_data = context.user_data.get('candidate_data')
            if not candidate_data:
                await update.message.reply_text("❌ Candidate data not found. Please start again.")
                return ADD_CANDIDATE
            
            # Get election
            try:
                election = Election.objects.get(id=candidate_data['election_id'])
            except Election.DoesNotExist:
                await update.message.reply_text("❌ Election not found. Please start again.")
                return ADMIN_ACTION
            
            # Create candidate
            candidate = Candidate(
                name=candidate_data['name'],
                position=candidate_data['position'],
                election=election
            )
            
            # Save image
            image_path = f"candidate_images/{candidate.id}.jpg"
            full_path = os.path.join(settings.MEDIA_ROOT, image_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            await file.download_to_drive(full_path)
            candidate.image = image_path
            candidate.save()
            
            await update.message.reply_text(f"✅ Candidate {candidate_data['name']} added for {candidate_data['position']} with photo.")
            del context.user_data['candidate_data']
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error adding candidate photo: {str(e)}")
            await update.message.reply_text(f"❌ Error uploading photo: {str(e)}. Please try again.")
            return ADD_CANDIDATE_PHOTO
    
    async def add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            admin_id = update.message.text.strip()
            Admin.objects.get_or_create(telegram_id=admin_id)
            await update.message.reply_text(f"✅ Admin {admin_id} added. They can now use /admin to register their face.")
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            await update.message.reply_text("❌ Invalid Telegram ID")
            return ADD_ADMIN
    
    async def remove_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            admin_id = update.message.text.strip()
            try:
                admin = Admin.objects.get(telegram_id=admin_id)
                admin.delete()
                await update.message.reply_text(f"✅ Admin {admin_id} removed")
            except Admin.DoesNotExist:
                await update.message.reply_text(f"❌ Admin {admin_id} not found")
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            await update.message.reply_text("❌ Invalid Telegram ID")
            return REMOVE_ADMIN
    
    async def voters(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        is_admin = Admin.objects.filter(telegram_id=user_id).exists() or context.user_data.get('is_admin', False)
        
        logger.info(f"User {user_id} requested /voters, is_admin={is_admin}")
        
        if is_admin:
            logger.info(f"Admin {user_id} authorized to add voter")
            try:
                # Create verification session
                session = VerificationSession.objects.create(
                    user_id=user_id,
                    session_type='voter_registration',
                    status='pending'
                )
                
                verification_url = f"{settings.BASE_URL}/verification/capture/{session.id}/"
                
                await update.message.reply_text(
                    f"📸 Voter Registration\n\n"
                    f"Please click the link below to capture voter face:\n"
                    f"{verification_url}\n\n"
                    f"This link will expire in 10 minutes.\n"
                    f"After capturing, return here and type /check_voter_registration"
                )
                context.user_data['voter_session_id'] = str(session.id)
                return WAITING_FACE_CAPTURE
            except Exception as e:
                logger.error(f"Voter registration session failed for user {user_id}: {e}")
                await update.message.reply_text("❌ Error initiating voter registration. Please try again later.")
                return ConversationHandler.END
        else:
            logger.warning(f"Non-admin {user_id} attempted to add voter")
            await update.message.reply_text("❌ Only admins can add voters.")
            return ConversationHandler.END
    
    async def check_voter_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        session_id = context.user_data.get('voter_session_id')
        if not session_id:
            await update.message.reply_text("No registration session found. Please use /voters to start.")
            return ConversationHandler.END
        
        try:
            session = VerificationSession.objects.get(id=session_id)
            
            if session.status == 'completed' and session.result and session.result.get('verified'):
                matric = session.result.get('matric')
                logger.info(f"Voter {matric} registered successfully")
                
                # Add voter to database
                Voter.objects.get_or_create(matric_number=matric)
                
                await update.message.reply_text(f"✅ Voter {matric} registered successfully")
                return ADMIN_ACTION
            elif session.status == 'completed' and session.result and not session.result.get('verified'):
                logger.warning(f"Voter registration failed")
                await update.message.reply_text("❌ Voter registration failed. Please try again.")
                return ConversationHandler.END
            elif session.status == 'expired':
                logger.warning(f"Voter registration session expired")
                await update.message.reply_text("❌ Registration session expired. Please start again with /voters.")
                return ConversationHandler.END
            else:
                await update.message.reply_text("⏳ Registration still in progress. Please complete the face capture and try again.")
                return WAITING_FACE_CAPTURE
        except VerificationSession.DoesNotExist:
            await update.message.reply_text("❌ Registration session not found. Please start again with /voters.")
            return ConversationHandler.END
    
    async def vote(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"User {update.effective_user.id} requested to vote")
        try:
            # Check if there are active elections
            active_elections = Election.objects.filter(status='active')
            if not active_elections:
                await update.message.reply_text("❌ No active elections available.")
                return ConversationHandler.END
            
            # Create verification session
            session = VerificationSession.objects.create(
                user_id=str(update.effective_user.id),
                session_type='vote',
                status='pending'
            )
            
            verification_url = f"{settings.BASE_URL}/verification/capture/{session.id}/"
            
            await update.message.reply_text(
                f"🗳️ Voter Verification Required\n\n"
                f"Please click the link below to complete face verification:\n"
                f"{verification_url}\n\n"
                f"This link will expire in 10 minutes.\n"
                f"After completing verification, return here and type /check_vote"
            )
            context.user_data['vote_session_id'] = str(session.id)
            return WAITING_FACE_CAPTURE
        except Exception as e:
            logger.error(f"Voter session creation failed for user {update.effective_user.id}: {e}")
            await update.message.reply_text("❌ Error initiating voter verification. Please try again later.")
            return ConversationHandler.END
    
    async def check_vote(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        session_id = context.user_data.get('vote_session_id')
        if not session_id:
            await update.message.reply_text("No verification session found. Please use /vote to start.")
            return ConversationHandler.END
        
        try:
            session = VerificationSession.objects.get(id=session_id)
            
            if session.status == 'completed' and session.result and session.result.get('verified'):
                matric = session.result.get('matric')
                logger.info(f"Voter {matric} verified successfully")
                
                # Check if voter exists in database
                if not Voter.objects.filter(matric_number=matric).exists():
                    logger.warning(f"Voter {matric} not in database")
                    await update.message.reply_text("❌ Voter not registered in database.")
                    return ConversationHandler.END
                
                context.user_data['matric'] = matric
                
                # Get active elections
                active_elections = Election.objects.filter(status='active')
                keyboard = [
                    [InlineKeyboardButton(election.title, callback_data=str(election.id))]
                    for election in active_elections
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("✅ Voter verified! Select an election:", reply_markup=reply_markup)
                return VOTER_VOTE
            elif session.status == 'completed' and session.result and not session.result.get('verified'):
                logger.warning(f"Voter verification failed for user {update.effective_user.id}")
                await update.message.reply_text("❌ Voter verification failed.")
                return ConversationHandler.END
            elif session.status == 'expired':
                logger.warning(f"Voter verification session expired for user {update.effective_user.id}")
                await update.message.reply_text("❌ Verification session expired. Please start again with /vote.")
                return ConversationHandler.END
            else:
                await update.message.reply_text("⏳ Verification still in progress. Please complete the face capture and try again.")
                return WAITING_FACE_CAPTURE
        except VerificationSession.DoesNotExist:
            await update.message.reply_text("❌ Verification session not found. Please start again with /vote.")
            return ConversationHandler.END
    
    async def voter_vote(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        election_id = query.data
        context.user_data['election_id'] = election_id
        
        try:
            # Get candidates for this election
            candidates = Candidate.objects.filter(election_id=election_id)
            if not candidates:
                logger.info(f"No candidates for election {election_id}")
                await query.message.reply_text("❌ No candidates available.")
                return ConversationHandler.END
            
            # Group candidates by position
            positions = {}
            for candidate in candidates:
                if candidate.position not in positions:
                    positions[candidate.position] = []
                positions[candidate.position].append((str(candidate.id), candidate.name))
            
            context.user_data['vote_stage'] = list(positions.keys())
            context.user_data['vote_data'] = {}
            context.user_data['candidates_by_position'] = positions
            
            await self.send_position(query, context)
            return VOTER_VOTE
        except Exception as e:
            logger.error(f"Error in voter_vote: {e}")
            await query.message.reply_text("❌ An error occurred. Please try again.")
            return ConversationHandler.END
    
    async def send_position(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stages = context.user_data.get('vote_stage', [])
        if not stages:
            await self.submit_vote(update, context)
            return
        
        pos = stages[0]
        context.user_data['current_position'] = pos
        candidates = context.user_data['candidates_by_position'][pos]
        
        buttons = [[InlineKeyboardButton(name, callback_data=cid)] for cid, name in candidates]
        await update.message.reply_text(f"Vote for: {pos}", reply_markup=InlineKeyboardMarkup(buttons))
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        # Check if this is a candidate selection
        if 'current_position' in context.user_data:
            candidate_id = query.data
            pos = context.user_data.get('current_position')
            context.user_data['vote_data'][pos] = candidate_id
            context.user_data['vote_stage'].pop(0)
            await self.send_position(query, context)
    
    async def submit_vote(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = context.user_data['vote_data']
        election_id = context.user_data['election_id']
        matric = context.user_data['matric']
        
        try:
            # Get voter
            voter = Voter.objects.get(matric_number=matric)
            election = Election.objects.get(id=election_id)
            
            # Check if voter has already voted in this election
            if Vote.objects.filter(matric_number=voter, election=election).exists():
                await query.message.reply_text("❌ You have already voted in this election.")
                return ConversationHandler.END
            
            # Cast votes for each position
            for pos, candidate_id in data.items():
                candidate = Candidate.objects.get(id=candidate_id)
                timestamp = timezone.now()
                vote_hash = Vote.generate_hash(matric, candidate_id, election_id, timestamp.isoformat())
                
                Vote.objects.create(
                    matric_number=voter,
                    election=election,
                    candidate=candidate,
                    vote_hash=vote_hash,
                    timestamp=timestamp
                )
            
            await query.message.reply_text(
                f"✅ Your votes have been submitted successfully!\n"
                f"Vote hash: {vote_hash[:16]}...\n"
                f"Keep this hash for verification purposes."
            )
        except Exception as e:
            logger.error(f"Error casting vote for {matric}: {e}")
            await query.message.reply_text("❌ Error casting vote. You may have already voted.")
        
        return ConversationHandler.END
    
    async def view_candidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        active_elections = Election.objects.filter(status__in=['pending', 'active'])
        if not active_elections:
            await update.message.reply_text("❌ No active elections available.")
            return ConversationHandler.END
        
        keyboard = [
            [InlineKeyboardButton(election.title, callback_data=f"view_cand_{election.id}")]
            for election in active_elections
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select an election to view candidates:", reply_markup=reply_markup)
        return VIEW_CANDIDATES
    
    async def view_candidates_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith("view_cand_"):
            election_id = query.data.replace("view_cand_", "")
            
            try:
                candidates = Candidate.objects.filter(election_id=election_id)
                if not candidates:
                    await query.message.reply_text("❌ No candidates available for this election.")
                    return ADMIN_ACTION if context.user_data.get('is_admin') else ConversationHandler.END
                
                for candidate in candidates:
                    message = f"Candidate: {candidate.name}\nPosition: {candidate.position}"
                    
                    try:
                        if candidate.image:
                            with open(os.path.join(settings.MEDIA_ROOT, candidate.image.name), 'rb') as photo:
                                await query.message.reply_photo(
                                    photo=InputFile(photo),
                                    caption=message
                                )
                        else:
                            await query.message.reply_text(message)
                    except Exception as e:
                        logger.error(f"Error sending candidate {candidate.name} image: {e}")
                        await query.message.reply_text(f"{message}\n⚠️ Image not available.")
            except Exception as e:
                logger.error(f"Error viewing candidates: {e}")
                await query.message.reply_text("❌ Error retrieving candidates.")
            
            return ADMIN_ACTION if context.user_data.get('is_admin') else ConversationHandler.END
    
    async def report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📝 Describe the issue you want to report:")
        return VOTER_REPORT
    
    async def submit_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        issue = update.message.text
        user_id = update.effective_user.id
        
        Report.objects.create(
            voter_id=str(user_id),
            issue=issue
        )
        
        logger.info(f"Report submitted by user {user_id}: {issue}")
        await update.message.reply_text("✅ Report submitted. Thank you!")
        return ConversationHandler.END
    
    async def results(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        elections = Election.objects.all()
        if not elections:
            await update.message.reply_text("❌ No elections found.")
            return
        
        for election in elections:
            if election.status == 'ended' or timezone.now() >= election.end_time:
                # Get vote counts
                candidates = Candidate.objects.filter(election=election)
                results_text = ""
                
                for candidate in candidates:
                    vote_count = Vote.objects.filter(candidate=candidate).count()
                    results_text += f"• {candidate.name} ({candidate.position}): {vote_count} votes\n"
                
                if results_text:
                    await update.message.reply_text(f"📊 Results for {election.title}:\n{results_text}")
                else:
                    await update.message.reply_text(f"📊 No votes for {election.title} yet.")
    
    async def add_voter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        matric = update.message.text.strip()
        
        try:
            Voter.objects.get_or_create(matric_number=matric)
            await update.message.reply_text(f"✅ Voter {matric} added to database. Use /voters to register their face.")
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error adding voter {matric}: {e}")
            await update.message.reply_text(f"❌ Error adding voter: {e}")
            return ADD_VOTER
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"User {update.effective_user.id} cancelled operation")
        await update.message.reply_text("❌ Operation cancelled.")
        return ConversationHandler.END
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}")
        if update and (update.message or update.callback_query):
            chat = update.message.chat if update.message else update.callback_query.message.chat
            await chat.send_message("❌ An unexpected error occurred. Please try again or contact support.")
