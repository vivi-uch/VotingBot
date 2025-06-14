import uuid
import hashlib
from django.db import models
from django.utils import timezone

class Voter(models.Model):
    matric_number = models.CharField(max_length=20, primary_key=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.matric_number

class Admin(models.Model):
    telegram_id = models.CharField(max_length=20, primary_key=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.telegram_id

class Election(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('ended', 'Ended'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        # Update status based on time
        now = timezone.now()
        if now < self.start_time:
            self.status = 'pending'
        elif now >= self.start_time and now <= self.end_time:
            self.status = 'active'
        else:
            self.status = 'ended'
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.title

class Candidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name='candidates')
    name = models.CharField(max_length=255)
    position = models.CharField(max_length=100)
    image = models.ImageField(upload_to='candidate_images/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} - {self.position}"

class Vote(models.Model):
    matric_number = models.ForeignKey(Voter, on_delete=models.CASCADE)
    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    vote_hash = models.CharField(max_length=64)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('matric_number', 'election')
    
    @staticmethod
    def generate_hash(matric, candidate_id, election_id, timestamp):
        vote_string = f"{matric}:{candidate_id}:{election_id}:{timestamp}"
        return hashlib.sha256(vote_string.encode()).hexdigest()
    
    def __str__(self):
        return f"{self.matric_number} - {self.election}"

class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    voter_id = models.CharField(max_length=100)
    issue = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Report {self.id} by {self.voter_id}"

class VerificationSession(models.Model):
    SESSION_TYPES = (
        ('admin', 'Admin Verification'),
        ('vote', 'Voter Verification'),
        ('voter_registration', 'Voter Registration'),
    )
    
    SESSION_STATUS = (
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('expired', 'Expired'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.CharField(max_length=100)
    session_type = models.CharField(max_length=20, choices=SESSION_TYPES)
    election = models.ForeignKey(Election, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=10, choices=SESSION_STATUS, default='pending')
    result = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            # Set expiration to 10 minutes from creation
            self.expires_at = timezone.now() + timezone.timedelta(minutes=10)
        super().save(*args, **kwargs)
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def __str__(self):
        return f"{self.session_type} session for {self.user_id}"
