import logging
import threading
import sys
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
from asgiref.sync import sync_to_async
from bot.models import Voter, Admin, Election, Candidate, Vote, Report, VerificationSession
from bot.services.face_recognition import FaceRecognizer
import os
import uuid

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
    SELECT_ELECTION_FOR_CANDIDATE,
    ENTER_CANDIDATE_DETAILS,
    SELECT_POSITION,
    VOTING_BY_POSITION,
) = range(18)

class Command(BaseCommand):
    help = 'Run the Telegram bot for e-voting'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.face_recognizer = None
        self.application = None
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--polling',
            action='store_true',
            help='Use polling instead of webhooks',
        )
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))
        
        # Check if bot token is configured
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stdout.write(self.style.ERROR('TELEGRAM_BOT_TOKEN not configured in settings'))
            return
        
        # Initialize face recognizer
        try:
            self.face_recognizer = FaceRecognizer()
            self.stdout.write(self.style.SUCCESS('Face recognizer initialized'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to initialize face recognizer: {e}'))
            self.stdout.write(self.style.WARNING('Bot will continue without face recognition'))
            self.face_recognizer = None
        
        # Run the bot using the simple synchronous approach
        try:
            self.run_bot_simple()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Bot stopped by user'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Bot error: {e}'))
    
    def run_bot_simple(self):
        """Run the bot using the simple synchronous approach"""
        try:
            # Test connectivity
            self.stdout.write("Testing connectivity...")
            import requests
            response = requests.get("https://api.telegram.org", timeout=10)
            self.stdout.write(self.style.SUCCESS("✅ Internet connection OK"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Internet connection issue: {e}"))
            return
        
        # Create the Application
        self.application = (
            Application.builder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .connect_timeout(30)
            .read_timeout(30)
            .write_timeout(30)
            .pool_timeout(30)
            .build()
        )
        
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
                ADMIN_ACTION: [
                    CallbackQueryHandler(self.admin_action),
                    CommandHandler('debug', self.debug_info)
                ],
                ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_admin)],
                REMOVE_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.remove_admin)],
                CREATE_ELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.create_election)],
                SELECT_ELECTION_FOR_CANDIDATE: [CallbackQueryHandler(self.select_election_for_candidate)],
                SELECT_POSITION: [CallbackQueryHandler(self.select_position)],
                ENTER_CANDIDATE_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.enter_candidate_details)],
                ADD_CANDIDATE_PHOTO: [
                    MessageHandler(filters.PHOTO, self.add_candidate_photo),
                    CommandHandler('skip', self.skip_candidate_photo)
                ],
                VOTER_VOTE: [
                    CallbackQueryHandler(self.voter_vote, pattern=r'^vote_election_[0-9a-f-]{36}$'),
                    CallbackQueryHandler(self.handle_position_selection, pattern=r'^select_position_.*$'),
                ],
                VOTING_BY_POSITION: [
                    CallbackQueryHandler(self.handle_candidate_selection, pattern=r'^vote_candidate_.*$'),
                    CallbackQueryHandler(self.handle_voting_navigation, pattern=r'^(next_position|prev_position|confirm_votes|cancel_votes)$'),
                ],
                VOTER_REPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.submit_report)],
                ADD_VOTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_voter)],
                VIEW_CANDIDATES: [CallbackQueryHandler(self.view_candidates_callback)],
                VIEW_REPORTS: [CallbackQueryHandler(self.admin_action)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
            conversation_timeout=300,
            per_chat=True,
            per_user=True,
        )
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler('results', self.results))
        self.application.add_error_handler(self.error_handler)
        
        # Start cleanup thread
        cleanup_thread = threading.Thread(target=self.cleanup_expired_sessions, daemon=True)
        cleanup_thread.start()
        
        self.stdout.write("Bot is starting... Press Ctrl+C to stop")
        
        # Start the Bot with polling
        self.application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            timeout=30,
            bootstrap_retries=3,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=30,
            pool_timeout=30
        )
    
    # Database operations wrapped with sync_to_async
    @sync_to_async
    def check_admin_db(self, telegram_id):
        return Admin.objects.filter(telegram_id=telegram_id).exists()
    
    @sync_to_async
    def create_admin_db(self, telegram_id):
        admin, created = Admin.objects.get_or_create(telegram_id=telegram_id)
        return created
    
    @sync_to_async
    def remove_admin_db(self, telegram_id):
        try:
            admin = Admin.objects.get(telegram_id=telegram_id)
            admin.delete()
            return True
        except Admin.DoesNotExist:
            return False
    
    @sync_to_async
    def create_voter_db(self, matric_number):
        voter, created = Voter.objects.get_or_create(matric_number=matric_number)
        return created
    
    @sync_to_async
    def check_voter_db(self, matric_number):
        return Voter.objects.filter(matric_number=matric_number).exists()
    
    @sync_to_async
    def create_election_db(self, title, start_time, end_time):
        election = Election.objects.create(
            title=title,
            start_time=start_time,
            end_time=end_time
        )
        return str(election.id)
    
    @sync_to_async
    def get_active_elections_db(self):
        elections = Election.objects.filter(status__in=['pending', 'active'])
        return [(str(e.id), e.title, e.start_time, e.end_time) for e in elections]
    
    @sync_to_async
    def get_all_elections_db(self):
        elections = Election.objects.all()
        return [(str(e.id), e.title, e.start_time, e.end_time, e.status) for e in elections]
    
    @sync_to_async
    def get_election_positions_db(self, election_id):
        """Get all unique positions for an election"""
        positions = Candidate.objects.filter(election_id=election_id).values_list('position', flat=True).distinct()
        return list(positions)
    
    @sync_to_async
    def create_candidate_db(self, name, position, election_id, image_path=None):
        try:
            election = Election.objects.get(id=election_id)
            
            candidate = Candidate(
                name=name,
                position=position,
                election=election
            )
            
            # Handle image if provided
            if image_path and os.path.exists(os.path.join(settings.MEDIA_ROOT, image_path)):
                candidate.image = image_path
            
            candidate.save()
            logger.info(f"Created candidate {name} for election {election_id}")
            return str(candidate.id)
            
        except Election.DoesNotExist:
            logger.error(f"Election {election_id} not found")
            return None
        except Exception as e:
            logger.error(f"Error creating candidate: {e}")
            return None
    
    @sync_to_async
    def get_candidates_by_position_db(self, election_id, position):
        """Get candidates for a specific position in an election"""
        try:
            candidates = Candidate.objects.filter(election_id=election_id, position=position)
            result = []
            for c in candidates:
                image_url = None
                if c.image:
                    try:
                        image_url = c.image.url
                    except:
                        image_url = None
                result.append((str(c.id), c.name, c.position, image_url))
            return result
        except Exception as e:
            logger.error(f"Error getting candidates: {e}")
            return []
    
    @sync_to_async
    def get_candidates_db(self, election_id):
        try:
            candidates = Candidate.objects.filter(election_id=election_id)
            result = []
            for c in candidates:
                image_url = None
                if c.image:
                    try:
                        image_url = c.image.url
                    except:
                        image_url = None
                result.append((str(c.id), c.name, c.position, image_url))
            return result
        except Exception as e:
            logger.error(f"Error getting candidates: {e}")
            return []
    
    @sync_to_async
    def create_report_db(self, voter_id, issue):
        report = Report.objects.create(voter_id=str(voter_id), issue=issue)
        return str(report.id)
    
    @sync_to_async
    def get_reports_db(self):
        reports = Report.objects.all()
        return [(str(r.id), r.voter_id, r.issue, r.timestamp) for r in reports]
    
    @sync_to_async
    def create_verification_session_db(self, user_id, session_type):
        session = VerificationSession.objects.create(
            user_id=str(user_id),
            session_type=session_type,
            status='pending'
        )
        return str(session.id)
    
    @sync_to_async
    def get_verification_session_db(self, session_id):
        try:
            session = VerificationSession.objects.get(id=session_id)
            return {
                'status': session.status,
                'result': session.result,
                'is_expired': session.is_expired()
            }
        except VerificationSession.DoesNotExist:
            return None
    
    @sync_to_async
    def check_voter_has_voted_db(self, matric, election_id):
        return Vote.objects.filter(matric_number=matric, election_id=election_id).exists()

    @sync_to_async
    def create_vote_db(self, matric, candidate_id, election_id, timestamp):
        try:
            import hashlib
            
            # Generate vote hash
            vote_string = f"{matric}:{candidate_id}:{election_id}:{timestamp}"
            vote_hash = hashlib.sha256(vote_string.encode()).hexdigest()
            
            # Create vote record
            vote = Vote.objects.create(
                matric_number_id=matric,
                candidate_id=candidate_id,
                election_id=election_id,
                vote_hash=vote_hash,
                timestamp=timezone.now()
            )
            return vote_hash
        except Exception as e:
            logger.error(f"Error creating vote: {e}")
            return None
    
    def cleanup_expired_sessions(self):
        """Clean up expired sessions periodically."""
        import time
        
        while True:
            try:
                time.sleep(60)
            except Exception as e:
                logger.error(f"Error in cleanup thread: {e}")
                time.sleep(60)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"User {user.id} started the bot")
        await update.message.reply_text(
            f"Hello {user.first_name}! Welcome to the E-Voting Bot.\n\n"
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
        
        # Check if user is admin in database first
        user_id = str(update.effective_user.id)
        is_admin = await self.check_admin_db(user_id)
        
        if not is_admin:
            await update.message.reply_text(
                f"❌ You are not registered as an admin. Your Telegram ID: {user_id}\n\n"
                f"Please contact the system administrator or run:\n"
                f"python create_admin.py"
            )
            return ConversationHandler.END
        
        try:
            # Create verification session
            session_id = await self.create_verification_session_db(user_id, 'admin')
            
            verification_url = f"{settings.BASE_URL}/verification/capture/{session_id}/"
            
            await update.message.reply_text(
                f"🔒 Admin Verification Required\n\n"
                f"Please click the link below to complete face verification:\n"
                f"{verification_url}\n\n"
                f"This link will expire in 10 minutes.\n"
                f"After completing verification, return here and type /check_admin"
            )
            context.user_data['admin_session_id'] = session_id
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
            session_data = await self.get_verification_session_db(session_id)
            
            if not session_data:
                await update.message.reply_text("❌ Verification session not found. Please start again with /admin.")
                return ConversationHandler.END
            
            if session_data['status'] == 'completed' and session_data['result'] and session_data['result'].get('verified'):
                logger.info(f"Admin {update.effective_user.id} verified successfully")
                context.user_data['is_admin'] = True
                
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
            elif session_data['status'] == 'completed' and session_data['result'] and not session_data['result'].get('verified'):
                logger.warning(f"Admin verification failed for user {update.effective_user.id}")
                await update.message.reply_text("❌ Admin verification failed. Access denied.")
                return ConversationHandler.END
            elif session_data['is_expired']:
                logger.warning(f"Admin verification session expired for user {update.effective_user.id}")
                await update.message.reply_text("❌ Verification session expired. Please start again with /admin.")
                return ConversationHandler.END
            else:
                await update.message.reply_text("⏳ Verification still in progress. Please complete the face capture and try again.")
                return WAITING_FACE_CAPTURE
        except Exception as e:
            logger.error(f"Error checking admin verification: {e}")
            await update.message.reply_text("❌ Error checking verification status.")
            return ConversationHandler.END
    
    async def admin_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        action = query.data
        
        if action == 'create_election':
            await query.message.reply_text(
                "📊 Create New Election\n\n"
                "Enter election details in this format:\n"
                "Title, YYYY-MM-DD HH:MM, YYYY-MM-DD HH:MM\n\n"
                "Example:\n"
                "Student Council Election, 2025-06-20 09:00, 2025-06-20 17:00"
            )
            return CREATE_ELECTION
            
        elif action == 'add_candidate':
            # Get active elections for candidate addition
            active_elections = await self.get_active_elections_db()
            if not active_elections:
                await query.message.reply_text("❌ No active elections available to add candidates.")
                return ADMIN_ACTION
            
            keyboard = [
                [InlineKeyboardButton(title, callback_data=f"select_election_{election_id}")]
                for election_id, title, _, _ in active_elections
            ]
            keyboard.append([InlineKeyboardButton("🔙 Back to Admin Menu", callback_data='back_to_admin')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("📋 Select an election to add a candidate:", reply_markup=reply_markup)
            return SELECT_ELECTION_FOR_CANDIDATE
            
        elif action == 'view_candidates':
            active_elections = await self.get_active_elections_db()
            if not active_elections:
                await query.message.reply_text("❌ No active elections available.")
                return ADMIN_ACTION
            
            keyboard = [
                [InlineKeyboardButton(title, callback_data=f"view_cand_{election_id}")]
                for election_id, title, _, _ in active_elections
            ]
            keyboard.append([InlineKeyboardButton("🔙 Back to Admin Menu", callback_data='back_to_admin')])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("👀 Select an election to view candidates:", reply_markup=reply_markup)
            return VIEW_CANDIDATES
            
        elif action == 'view_reports':
            reports = await self.get_reports_db()
            if not reports:
                await query.message.reply_text("❌ No reports available.")
                return ADMIN_ACTION
            
            report_text = "📋 Voter Reports:\n\n"
            for report_id, voter_id, issue, timestamp in reports[:10]:  # Limit to 10 reports
                report_text += f"**Report ID:** {report_id[:8]}...\n"
                report_text += f"**Voter ID:** {voter_id}\n"
                report_text += f"**Issue:** {issue[:100]}...\n"
                report_text += f"**Time:** {timestamp}\n\n"
            
            if len(reports) > 10:
                report_text += f"... and {len(reports) - 10} more reports"
            
            # Add back button
            keyboard = [[InlineKeyboardButton("🔙 Back to Admin Menu", callback_data='back_to_admin')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(report_text, reply_markup=reply_markup)
            return ADMIN_ACTION
            
        elif action == 'add_admin':
            await query.message.reply_text(
                "👤 Add New Admin\n\n"
                "Enter the Telegram ID of the new admin:\n"
                "(You can get this from @userinfobot)"
            )
            return ADD_ADMIN
            
        elif action == 'remove_admin':
            await query.message.reply_text(
                "🗑️ Remove Admin\n\n"
                "Enter the Telegram ID of the admin to remove:"
            )
            return REMOVE_ADMIN
            
        elif action == 'add_voter':
            await query.message.reply_text(
                "🗳️ Add New Voter\n\n"
                "Enter the voter's matric number:\n"
                "(Example: STU001, STU002, etc.)"
            )
            return ADD_VOTER
            
        elif action == 'back_to_admin':
            # Return to admin menu
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
            await query.message.reply_text("🔧 Admin Panel - Choose an action:", reply_markup=reply_markup)
            return ADMIN_ACTION
        
        return ADMIN_ACTION
    
    async def select_election_for_candidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'back_to_admin':
            return await self.admin_action(update, context)
        
        if query.data.startswith('select_election_'):
            election_id = query.data.replace('select_election_', '')
            context.user_data['selected_election_id'] = election_id
            
            # Get existing positions for this election
            positions = await self.get_election_positions_db(election_id)
            
            message = "📍 Select Position for Candidate\n\n"
            if positions:
                message += "Existing positions:\n"
                for pos in positions:
                    message += f"• {pos}\n"
                message += "\n"
            
            # Create buttons for existing positions + option to add new
            keyboard = []
            for position in positions:
                keyboard.append([InlineKeyboardButton(f"📍 {position}", callback_data=f"position_{position}")])
            
            keyboard.append([InlineKeyboardButton("➕ Add New Position", callback_data="new_position")])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='back_to_admin')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(message, reply_markup=reply_markup)
            return SELECT_POSITION
        
        return SELECT_ELECTION_FOR_CANDIDATE
    
    async def select_position(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'back_to_admin':
            return await self.admin_action(update, context)
        elif query.data == 'new_position':
            await query.message.reply_text(
                "📍 Enter New Position\n\n"
                "Enter the position name (e.g., President, Vice President, Secretary, etc.):"
            )
            context.user_data['awaiting_new_position'] = True
            return ENTER_CANDIDATE_DETAILS
        elif query.data.startswith('position_'):
            position = query.data.replace('position_', '')
            context.user_data['selected_position'] = position
            
            await query.message.reply_text(
                f"👤 Add Candidate for {position}\n\n"
                f"Enter candidate name:"
            )
            return ENTER_CANDIDATE_DETAILS
        
        return SELECT_POSITION
    
    async def enter_candidate_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            input_text = update.message.text.strip()
            
            # Check if we're waiting for a new position name
            if context.user_data.get('awaiting_new_position'):
                context.user_data['selected_position'] = input_text
                context.user_data['awaiting_new_position'] = False
                
                await update.message.reply_text(
                    f"📍 Position: {input_text}\n\n"
                    f"Now enter the candidate name:"
                )
                return ENTER_CANDIDATE_DETAILS
            
            # We have the candidate name
            name = input_text
            position = context.user_data.get('selected_position')
            election_id = context.user_data.get('selected_election_id')
            
            if not position or not election_id:
                await update.message.reply_text("❌ Missing position or election. Please start again.")
                return ADMIN_ACTION
            
            # Store candidate data for photo upload
            context.user_data['candidate_data'] = {
                'name': name,
                'position': position,
                'election_id': election_id
            }
            
            await update.message.reply_text(
                f"📸 Candidate Details Received\n\n"
                f"**Name:** {name}\n"
                f"**Position:** {position}\n\n"
                f"Please upload a photo of the candidate (JPEG/PNG format).\n"
                f"Or send /skip to add candidate without photo."
            )
            return ADD_CANDIDATE_PHOTO
            
        except Exception as e:
            logger.error(f"Error processing candidate details: {e}")
            await update.message.reply_text("❌ Error processing candidate details. Please try again.")
            return ENTER_CANDIDATE_DETAILS
    
    async def skip_candidate_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle skipping candidate photo"""
        return await self.add_candidate_photo(update, context, skip_photo=True)
    
    async def add_candidate_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE, skip_photo=False):
        try:
            candidate_data = context.user_data.get('candidate_data')
            if not candidate_data:
                await update.message.reply_text("❌ Candidate data not found. Please start again.")
                return ADMIN_ACTION

            image_path = None

            if skip_photo or (update.message.text and update.message.text.strip() == '/skip'):
                await update.message.reply_text("⏳ Adding candidate without photo...")
            elif update.message.photo:
                await update.message.reply_text("📸 Photo received! Processing...")
                
                # Handle photo upload
                photo = update.message.photo[-1]  # Get highest resolution
                file = await photo.get_file()
                
                # Create candidate images directory
                candidate_images_dir = os.path.join(settings.MEDIA_ROOT, 'candidate_images')
                os.makedirs(candidate_images_dir, exist_ok=True)
                
                # Generate unique filename
                candidate_id = str(uuid.uuid4())
                image_filename = f"{candidate_id}.jpg"
                full_image_path = os.path.join(candidate_images_dir, image_filename)
                
                try:
                    # Download and save the image
                    await file.download_to_drive(full_image_path)
                    image_path = f"candidate_images/{image_filename}"  # Relative path for database
                    await update.message.reply_text("✅ Photo uploaded successfully!")
                except Exception as e:
                    logger.error(f"Error downloading photo: {e}")
                    await update.message.reply_text("⚠️ Photo upload failed, continuing without photo...")
                    image_path = None
            else:
                await update.message.reply_text(
                    "❌ Please upload a photo or send /skip to continue without photo."
                )
                return ADD_CANDIDATE_PHOTO

            # Create candidate in database
            await update.message.reply_text("⏳ Creating candidate in database...")
            
            try:
                candidate_id = await self.create_candidate_db(
                    candidate_data['name'],
                    candidate_data['position'],
                    candidate_data['election_id'],
                    image_path
                )
                
                if candidate_id:
                    await update.message.reply_text(
                        f"✅ Candidate Added Successfully!\n\n"
                        f"**Name:** {candidate_data['name']}\n"
                        f"**Position:** {candidate_data['position']}\n"
                        f"**Photo:** {'✅ Uploaded' if image_path else '❌ No photo'}\n"
                        f"**Candidate ID:** {candidate_id[:8]}...\n\n"
                        f"Returning to admin menu..."
                    )
                    
                    # Show admin menu again
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
                    await update.message.reply_text("🔧 Admin Panel - Choose an action:", reply_markup=reply_markup)
                else:
                    await update.message.reply_text("❌ Error creating candidate. Election may not exist.")
                    
            except Exception as e:
                logger.error(f"Error creating candidate in database: {e}")
                await update.message.reply_text(f"❌ Database error: {str(e)}")

            # Clean up user data
            if 'candidate_data' in context.user_data:
                del context.user_data['candidate_data']
            if 'selected_election_id' in context.user_data:
                del context.user_data['selected_election_id']
            if 'selected_position' in context.user_data:
                del context.user_data['selected_position']

            return ADMIN_ACTION

        except Exception as e:
            logger.error(f"Error in add_candidate_photo: {e}")
            await update.message.reply_text(f"❌ Unexpected error: {str(e)}")
            return ADD_CANDIDATE_PHOTO
    
    async def create_election(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            input_text = update.message.text
            title, start_time, end_time = [x.strip() for x in input_text.split(',')]
            start_time = timezone.datetime.strptime(start_time, '%Y-%m-%d %H:%M')
            end_time = timezone.datetime.strptime(end_time, '%Y-%m-%d %H:%M')
            
            if end_time <= start_time:
                raise ValueError("End time must be after start time")
            
            # Make timezone aware
            start_time = timezone.make_aware(start_time)
            end_time = timezone.make_aware(end_time)
            
            election_id = await self.create_election_db(title, start_time, end_time)
            await update.message.reply_text(f"✅ Election '{title}' created successfully!\nElection ID: {election_id}")
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error creating election: {str(e)}")
            await update.message.reply_text(f"❌ Invalid format: {str(e)}. Use: Title, YYYY-MM-DD HH:MM, YYYY-MM-DD HH:MM")
            return CREATE_ELECTION
    
    async def add_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            admin_id = update.message.text.strip()
            if not admin_id.isdigit():
                await update.message.reply_text("❌ Telegram ID should be a number")
                return ADD_ADMIN
            
            created = await self.create_admin_db(admin_id)
            if created:
                await update.message.reply_text(f"✅ Admin {admin_id} added successfully!")
            else:
                await update.message.reply_text(f"ℹ️ Admin {admin_id} already exists.")
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            await update.message.reply_text("❌ Error adding admin")
            return ADD_ADMIN
    
    async def remove_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            admin_id = update.message.text.strip()
            removed = await self.remove_admin_db(admin_id)
            if removed:
                await update.message.reply_text(f"✅ Admin {admin_id} removed successfully!")
            else:
                await update.message.reply_text(f"❌ Admin {admin_id} not found")
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            await update.message.reply_text("❌ Error removing admin")
            return REMOVE_ADMIN
    
    async def add_voter(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            matric = update.message.text.strip().upper()
            created = await self.create_voter_db(matric)
            if created:
                await update.message.reply_text(f"✅ Voter {matric} added successfully!")
            else:
                await update.message.reply_text(f"ℹ️ Voter {matric} already exists.")
            return ADMIN_ACTION
        except Exception as e:
            logger.error(f"Error adding voter: {e}")
            await update.message.reply_text("❌ Error adding voter")
            return ADD_VOTER
    
    async def debug_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Debug command to show current state"""
        user_data = context.user_data
        debug_msg = "🔍 Debug Info:\n\n"
        debug_msg += f"User Data: {user_data}\n"
        debug_msg += f"Chat ID: {update.effective_chat.id}\n"
        debug_msg += f"User ID: {update.effective_user.id}\n"
        
        # Check elections
        elections = await self.get_active_elections_db()
        debug_msg += f"Active Elections: {len(elections)}\n"
    
        await update.message.reply_text(debug_msg)
    
    async def vote(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"User {update.effective_user.id} requested to vote")
        
        # Check if there are active elections
        try:
            active_elections = await self.get_active_elections_db()
            if not active_elections:
                await update.message.reply_text("❌ No active elections available at this time.")
                return ConversationHandler.END
            
            # Create verification session for voting
            user_id = str(update.effective_user.id)
            session_id = await self.create_verification_session_db(user_id, 'vote')
            
            verification_url = f"{settings.BASE_URL}/verification/capture/{session_id}/"
            
            await update.message.reply_text(
                f"🗳️ Voter Verification Required\n\n"
                f"Please click the link below to complete face verification:\n"
                f"{verification_url}\n\n"
                f"This link will expire in 10 minutes.\n"
                f"After completing verification, return here and type /check_vote"
            )
            context.user_data['vote_session_id'] = session_id
            return WAITING_FACE_CAPTURE
            
        except Exception as e:
            logger.error(f"Vote session creation failed for user {update.effective_user.id}: {e}")
            await update.message.reply_text("❌ Error initiating voter verification. Please try again later.")
            return ConversationHandler.END

    async def check_vote(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        session_id = context.user_data.get('vote_session_id')
        if not session_id:
            await update.message.reply_text("No verification session found. Please use /vote to start.")
            return ConversationHandler.END
        
        try:
            session_data = await self.get_verification_session_db(session_id)
            
            if not session_data:
                await update.message.reply_text("❌ Verification session not found. Please start again with /vote.")
                return ConversationHandler.END
            
            if session_data['status'] == 'completed' and session_data['result'] and session_data['result'].get('verified'):
                matric = session_data['result'].get('matric')
                logger.info(f"Voter {matric} verified successfully")
                
                # Check if voter exists in database
                voter_exists = await self.check_voter_db(matric)
                if not voter_exists:
                    await update.message.reply_text("❌ Voter not registered in database. Please contact an administrator.")
                    return ConversationHandler.END
                
                context.user_data['verified_matric'] = matric
                
                # Show available elections
                active_elections = await self.get_active_elections_db()
                if not active_elections:
                    await update.message.reply_text("❌ No active elections available.")
                    return ConversationHandler.END
                
                keyboard = [
                    [InlineKeyboardButton(title, callback_data=f"vote_election_{election_id}")]
                    for election_id, title, _, _ in active_elections
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"✅ Voter verified! Welcome {matric}\n\n"
                    f"Select an election to vote in:",
                    reply_markup=reply_markup
                )
                return VOTER_VOTE
            
            elif session_data['status'] == 'completed' and session_data['result'] and not session_data['result'].get('verified'):
                logger.warning(f"Voter verification failed for user {update.effective_user.id}")
                await update.message.reply_text("❌ Voter verification failed. Please ensure you are registered and try again.")
                return ConversationHandler.END
            elif session_data['is_expired']:
                logger.warning(f"Voter verification session expired for user {update.effective_user.id}")
                await update.message.reply_text("❌ Verification session expired. Please start again with /vote.")
                return ConversationHandler.END
            else:
                await update.message.reply_text("⏳ Verification still in progress. Please complete the face capture and try again.")
                return WAITING_FACE_CAPTURE
            
        except Exception as e:
            logger.error(f"Error checking vote verification: {e}")
            await update.message.reply_text("❌ Error checking verification status.")
            return ConversationHandler.END

    async def voter_vote(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith('vote_election_'):
            election_id = query.data.replace('vote_election_', '')
            context.user_data['selected_election_id'] = election_id
            
            # Check if voter has already voted
            matric = context.user_data.get('verified_matric')
            has_voted = await self.check_voter_has_voted_db(matric, election_id)
            if has_voted:
                await query.message.reply_text("❌ You have already voted in this election.")
                return ConversationHandler.END
            
            # Get positions for this election
            positions = await self.get_election_positions_db(election_id)
            if not positions:
                await query.message.reply_text("❌ No positions available for this election.")
                return ConversationHandler.END
            
            context.user_data['positions'] = positions
            context.user_data['votes'] = {}
            context.user_data['current_position_index'] = 0
            
            # Show first position
            await self.show_position_voting(query, context)
            return VOTING_BY_POSITION
        
        return VOTER_VOTE

    async def handle_position_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle position selection during voting"""
        query = update.callback_query
        await query.answer()
        
        # This is handled by voter_vote method
        return await self.voter_vote(update, context)

    async def handle_candidate_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle candidate selection for current position"""
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith('vote_candidate_'):
            candidate_id = query.data.replace('vote_candidate_', '')
            current_position = context.user_data['positions'][context.user_data['current_position_index']]
            context.user_data['votes'][current_position] = candidate_id
            
            await query.message.reply_text(f"✅ Vote recorded for {current_position}")
            
            # Move to next position or show summary
            context.user_data['current_position_index'] += 1
            
            if context.user_data['current_position_index'] < len(context.user_data['positions']):
                # More positions to vote for
                await self.show_position_voting(query, context)
                return VOTING_BY_POSITION
            else:
                # All positions voted, show summary
                await self.show_vote_summary(query, context)
                return VOTING_BY_POSITION
        
        return VOTING_BY_POSITION

    async def handle_voting_navigation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voting navigation (next, prev, confirm, cancel)"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'confirm_votes':
            await self.submit_votes(query, context)
            return ConversationHandler.END
        elif query.data == 'cancel_votes':
            await query.message.reply_text("❌ Voting cancelled.")
            return ConversationHandler.END
        elif query.data == 'next_position':
            context.user_data['current_position_index'] += 1
            await self.show_position_voting(query, context)
            return VOTING_BY_POSITION
        elif query.data == 'prev_position':
            context.user_data['current_position_index'] -= 1
            await self.show_position_voting(query, context)
            return VOTING_BY_POSITION
        
        return VOTING_BY_POSITION

    async def show_position_voting(self, query, context):
        """Show candidates for current position with images"""
        current_position = context.user_data['positions'][context.user_data['current_position_index']]
        election_id = context.user_data['selected_election_id']
        
        # Get candidates for this position
        candidates = await self.get_candidates_by_position_db(election_id, current_position)
        
        if not candidates:
            await query.message.reply_text(f"❌ No candidates available for {current_position}")
            return
        
        # Send position header
        position_num = context.user_data['current_position_index'] + 1
        total_positions = len(context.user_data['positions'])
        
        await query.message.reply_text(
            f"🗳️ **Position {position_num}/{total_positions}: {current_position}**\n\n"
            f"Select your candidate:"
        )
        
        # Send each candidate with image
        keyboard = []
        for candidate_id, name, position, image_url in candidates:
            # Send candidate image if available
            if image_url:
                try:
                    # Convert relative URL to full path for sending
                    image_path = os.path.join(settings.MEDIA_ROOT, image_url.lstrip('/media/'))
                    if os.path.exists(image_path):
                        with open(image_path, 'rb') as photo:
                            await query.message.reply_photo(
                                photo=photo,
                                caption=f"👤 **{name}**\n📍 {position}"
                            )
                    else:
                        await query.message.reply_text(f"👤 **{name}**\n📍 {position}\n📸 Image not available")
                except Exception as e:
                    logger.error(f"Error sending candidate image: {e}")
                    await query.message.reply_text(f"👤 **{name}**\n📍 {position}\n📸 Image error")
            else:
                await query.message.reply_text(f"👤 **{name}**\n📍 {position}")
            
            # Add vote button for this candidate
            keyboard.append([InlineKeyboardButton(f"Vote for {name}", callback_data=f"vote_candidate_{candidate_id}")])
        
        # Add navigation buttons
        nav_buttons = []
        if context.user_data['current_position_index'] > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data='prev_position'))
        
        nav_buttons.append(InlineKeyboardButton("❌ Cancel", callback_data='cancel_votes'))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Choose your candidate:", reply_markup=reply_markup)

    async def show_vote_summary(self, query, context):
        """Show voting summary before final submission"""
        votes = context.user_data['votes']
        election_id = context.user_data['selected_election_id']
        
        summary = "📋 **Vote Summary**\n\n"
        
        # Get candidate names for each vote
        for position, candidate_id in votes.items():
            candidates = await self.get_candidates_by_position_db(election_id, position)
            candidate_name = "Unknown"
            for cid, name, _, _ in candidates:
                if cid == candidate_id:
                    candidate_name = name
                    break
            summary += f"**{position}:** {candidate_name}\n"
        
        summary += "\n⚠️ **Please review your votes carefully.**\n"
        summary += "Once submitted, they cannot be changed."
        
        keyboard = [
            [InlineKeyboardButton("✅ Confirm & Submit Votes", callback_data='confirm_votes')],
            [InlineKeyboardButton("❌ Cancel", callback_data='cancel_votes')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(summary, reply_markup=reply_markup, parse_mode='Markdown')

    async def submit_votes(self, query, context):
        """Submit the votes to database"""
        try:
            matric = context.user_data.get('verified_matric')
            election_id = context.user_data.get('selected_election_id')
            votes = context.user_data.get('votes', {})
            
            if not matric or not election_id or not votes:
                await query.message.reply_text("❌ Missing voting data. Please start again.")
                return
            
            # Submit votes
            vote_hashes = []
            for position, candidate_id in votes.items():
                timestamp = timezone.now().isoformat()
                vote_hash = await self.create_vote_db(matric, candidate_id, election_id, timestamp)
                if vote_hash:
                    vote_hashes.append(vote_hash[:16])
            
            if vote_hashes:
                await query.message.reply_text(
                    f"✅ **Your votes have been submitted successfully!**\n\n"
                    f"🔐 Vote confirmation: {', '.join(vote_hashes)}...\n\n"
                    f"🎉 Thank you for participating in the election!\n"
                    f"Keep your confirmation code for verification purposes.",
                    parse_mode='Markdown'
                )
            else:
                await query.message.reply_text("❌ Error submitting votes. Please try again or contact support.")
        
        except Exception as e:
            logger.error(f"Error submitting votes: {e}")
            await query.message.reply_text("❌ Error submitting votes. Please contact support.")
    
    async def voters(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("👥 Voter registration feature coming soon!")
        return ConversationHandler.END
    
    async def report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📝 Describe the issue you want to report:")
        return VOTER_REPORT
    
    async def submit_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        issue = update.message.text
        user_id = update.effective_user.id
        report_id = await self.create_report_db(user_id, issue)
        await update.message.reply_text(f"✅ Report submitted successfully! Report ID: {report_id}")
        return ConversationHandler.END
    
    async def view_candidate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        active_elections = await self.get_active_elections_db()
        if not active_elections:
            await update.message.reply_text("❌ No active elections available.")
            return ConversationHandler.END
        
        keyboard = [
            [InlineKeyboardButton(title, callback_data=f"view_cand_{election_id}")]
            for election_id, title, _, _ in active_elections
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("👀 Select an election to view candidates:", reply_markup=reply_markup)
        return VIEW_CANDIDATES
    
    async def view_candidates_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'back_to_admin':
            return await self.admin_action(update, context)
        
        if query.data.startswith("view_cand_"):
            election_id = query.data.replace("view_cand_", "")
            candidates = await self.get_candidates_db(election_id)
            
            if not candidates:
                await query.message.reply_text("❌ No candidates found for this election.")
            else:
                # Group candidates by position
                positions = {}
                for candidate_id, name, position, image_url in candidates:
                    if position not in positions:
                        positions[position] = []
                    positions[position].append((candidate_id, name, image_url))
                
                # Send candidates by position
                for position, position_candidates in positions.items():
                    await query.message.reply_text(f"📍 **{position}**")
                    
                    for candidate_id, name, image_url in position_candidates:
                        # Send candidate with image
                        if image_url:
                            try:
                                # Convert relative URL to full path
                                image_path = os.path.join(settings.MEDIA_ROOT, image_url.lstrip('/media/'))
                                if os.path.exists(image_path):
                                    with open(image_path, 'rb') as photo:
                                        await query.message.reply_photo(
                                            photo=photo,
                                            caption=f"👤 **{name}**\n📍 {position}\n🆔 {candidate_id[:8]}..."
                                        )
                                else:
                                    await query.message.reply_text(
                                        f"👤 **{name}**\n📍 {position}\n🆔 {candidate_id[:8]}...\n📸 Image not found"
                                    )
                            except Exception as e:
                                logger.error(f"Error sending candidate image: {e}")
                                await query.message.reply_text(
                                    f"👤 **{name}**\n📍 {position}\n🆔 {candidate_id[:8]}...\n📸 Image error"
                                )
                        else:
                            await query.message.reply_text(
                                f"👤 **{name}**\n📍 {position}\n🆔 {candidate_id[:8]}...\n📸 No image"
                            )
            
            # Add back button if this is admin view
            if context.user_data.get('is_admin'):
                keyboard = [[InlineKeyboardButton("🔙 Back to Admin Menu", callback_data='back_to_admin')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("Candidates displayed above.", reply_markup=reply_markup)
                return ADMIN_ACTION
        
        return ConversationHandler.END
    
    async def results(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            elections = await self.get_all_elections_db()
            if elections:
                message = "📊 Election Results\n\n"
                for election_id, title, start_time, end_time, status in elections:
                    message += f"• **{title}**\n"
                    message += f"  Status: {status}\n"
                    message += f"  Start: {start_time}\n"
                    message += f"  End: {end_time}\n\n"
            else:
                message = "📊 No elections found."
            
            await update.message.reply_text(message)
        except Exception as e:
            logger.error(f"Error getting results: {e}")
            await update.message.reply_text("❌ Error retrieving results.")
    
    async def check_voter_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Voter registration checking feature coming soon!")
        return ConversationHandler.END
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ Operation cancelled.")
        return ConversationHandler.END
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}")
        try:
            if update and (update.message or update.callback_query):
                chat = update.message.chat if update.message else update.callback_query.message.chat
                await context.bot.send_message(
                    chat_id=chat.id,
                    text="❌ An unexpected error occurred. Please try again or contact support."
                )
        except Exception as e:
            logger.error(f"Error in error handler: {e}")
