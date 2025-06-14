# E-Voting Django Project

A Django-based implementation of an E-Voting system with face recognition for voter verification.

## Features

- Telegram bot integration for voting and administration
- Face recognition for voter and admin verification
- Election management (create elections, add candidates)
- Secure voting with cryptographic vote hashing
- Web interface for face capture and verification

## Installation

1. Clone the repository:
\`\`\`bash
git clone https://github.com/yourusername/evoting-django.git
cd evoting-django
\`\`\`

2. Create a virtual environment and activate it:
\`\`\`bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
\`\`\`

3. Install dependencies:
\`\`\`bash
pip install -r requirements.txt
\`\`\`

4. Install dlib shape predictor:
\`\`\`bash
mkdir -p media/models/dlib
# Download shape_predictor_68_face_landmarks.dat and place it in media/models/dlib/
\`\`\`

5. Apply migrations:
\`\`\`bash
python manage.py migrate
\`\`\`

6. Create a superuser:
\`\`\`bash
python manage.py createsuperuser
\`\`\`

7. Run the development server:
\`\`\`bash
python manage.py runserver
\`\`\`

8. In a separate terminal, run the Telegram bot:
\`\`\`bash
python manage.py run_bot
\`\`\`

## Configuration

1. Update `settings.py` with your Telegram bot token:
```python
TELEGRAM_BOT_TOKEN = 'your_bot_token_here'
