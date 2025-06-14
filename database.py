import sqlite3
from datetime import datetime
import uuid
import logging

logging.basicConfig(
    filename='logs/bot.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        # Create tables if they don't exist
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS voters (
                matric_number TEXT PRIMARY KEY
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                telegram_id TEXT PRIMARY KEY
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS elections (
                id TEXT PRIMARY KEY,
                title TEXT,
                start_time TEXT,
                end_time TEXT,
                status TEXT
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY,
                election_id TEXT,
                name TEXT,
                position TEXT
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS votes (
                matric_number TEXT,
                election_id TEXT,
                candidate_id TEXT,
                vote_hash TEXT,
                timestamp TEXT,
                UNIQUE(matric_number, election_id)
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                voter_id TEXT,
                issue TEXT,
                timestamp TEXT
            )
        ''')
        # Add image_path column to candidates if it doesn't exist
        try:
            self.cursor.execute("PRAGMA table_info(candidates)")
            columns = [info[1] for info in self.cursor.fetchall()]
            if 'image_path' not in columns:
                self.cursor.execute("ALTER TABLE candidates ADD COLUMN image_path TEXT")
                logger.info("Added image_path column to candidates table")
            else:
                logger.info("image_path column already exists in candidates table")
        except Exception as e:
            logger.error(f"Error updating candidates table schema: {e}")
            raise
        self.conn.commit()

    def add_voter(self, matric_number):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO voters (matric_number) VALUES (?)", (matric_number,))
            self.conn.commit()
            logger.info(f"Voter {matric_number} added")
        except Exception as e:
            logger.error(f"Error adding voter {matric_number}: {e}")
            raise

    def is_voter_registered(self, matric_number):
        self.cursor.execute("SELECT 1 FROM voters WHERE matric_number = ?", (matric_number,))
        return self.cursor.fetchone() is not None

    def voter_exists(self, matric_number):
        return self.is_voter_registered(matric_number)

    def add_admin_id(self, telegram_id):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (str(telegram_id),))
            self.conn.commit()
            logger.info(f"Admin {telegram_id} added")
        except Exception as e:
            logger.error(f"Error adding admin {telegram_id}: {e}")
            raise

    def remove_admin_id(self, telegram_id):
        try:
            self.cursor.execute("DELETE FROM admins WHERE telegram_id = ?", (str(telegram_id),))
            self.conn.commit()
            logger.info(f"Admin {telegram_id} removed")
        except Exception as e:
            logger.error(f"Error removing admin {telegram_id}: {e}")
            raise

    def is_admin(self, telegram_id):
        self.cursor.execute("SELECT 1 FROM admins WHERE telegram_id = ?", (str(telegram_id),))
        return self.cursor.fetchone() is not None

    def create_election(self, name, start_time, end_time):
        try:
            election_id = str(uuid.uuid4())
            status = "pending" if start_time > datetime.now() else "active"
            self.cursor.execute(
                "INSERT INTO elections (id, title, start_time, end_time, status) VALUES (?, ?, ?, ?, ?)",
                (election_id, name, start_time.isoformat(), end_time.isoformat(), status)
            )
            self.conn.commit()
            logger.info(f"Election {name} created with ID {election_id}")
            return election_id
        except Exception as e:
            logger.error(f"Error creating election {name}: {e}")
            raise

    def end_election(self, election_id):
        try:
            self.cursor.execute(
                "UPDATE elections SET status = 'ended' WHERE id = ?",
                (election_id,)
            )
            self.conn.commit()
            logger.info(f"Election {election_id} ended")
        except Exception as e:
            logger.error(f"Error ending election {election_id}: {e}")
            raise

    def get_election_results(self, election_id):
        try:
            self.cursor.execute('''
                SELECT c.id, c.name, c.position, COUNT(v.candidate_id) as vote_count
                FROM candidates c
                LEFT JOIN votes v ON c.id = v.candidate_id AND c.election_id = v.election_id
                WHERE c.election_id = ?
                GROUP BY c.id
            ''', (election_id,))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting results for election {election_id}: {e}")
            raise

    def add_candidate(self, name, position, election_id, image_path=None):
        try:
            candidate_id = str(uuid.uuid4())
            self.cursor.execute(
                "INSERT INTO candidates (id, election_id, name, position, image_path) VALUES (?, ?, ?, ?, ?)",
                (candidate_id, election_id, name, position, image_path)
            )
            self.conn.commit()
            logger.info(f"Candidate {name} added to election {election_id} with image {image_path}")
            return candidate_id
        except Exception as e:
            logger.error(f"Error adding candidate {name} to election {election_id}: {e}")
            raise

    def cast_vote(self, matric_number, candidate_id, election_id, vote_hash, timestamp):
        try:
            self.cursor.execute(
                "INSERT INTO votes (matric_number, election_id, candidate_id, vote_hash, timestamp) VALUES (?, ?, ?, ?, ?)",
                (matric_number, election_id, candidate_id, vote_hash, timestamp)
            )
            self.conn.commit()
            logger.info(f"Vote cast by {matric_number} for candidate {candidate_id} in election {election_id}")
        except Exception as e:
            logger.error(f"Error casting vote for {matric_number}: {e}")
            raise

    def store_report(self, voter_id, issue):
        try:
            report_id = str(uuid.uuid4())
            timestamp = datetime.now().isoformat()
            self.cursor.execute(
                "INSERT INTO reports (id, voter_id, issue, timestamp) VALUES (?, ?, ?, ?)",
                (report_id, str(voter_id), issue, timestamp)
            )
            self.conn.commit()
            logger.info(f"Report stored for voter {voter_id}")
        except Exception as e:
            logger.error(f"Error storing report for voter {voter_id}: {e}")
            raise

    def get_active_elections(self):
        try:
            now = datetime.now().isoformat()
            self.cursor.execute(
                "SELECT id, title, start_time, end_time FROM elections WHERE start_time <= ? AND end_time >= ?",
                (now, now)
            )
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting active elections: {e}")
            raise

    def get_all_elections(self):
        try:
            self.cursor.execute("SELECT id, title, start_time, end_time FROM elections")
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting all elections: {e}")
            raise

    def get_candidates(self, election_id):
        try:
            self.cursor.execute(
                "SELECT id, name, position, image_path FROM candidates WHERE election_id = ?",
                (election_id,)
            )
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting candidates for election {election_id}: {e}")
            raise

    def get_vote_counts(self, election_id):
        return self.get_election_results(election_id)

    def get_reports(self):
        try:
            self.cursor.execute("SELECT id, voter_id, issue, timestamp FROM reports")
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting reports: {e}")
            raise

    def __del__(self):
        try:
            self.conn.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database: {e}")
