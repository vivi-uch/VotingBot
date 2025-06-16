#!/usr/bin/env python
"""
Update election status based on current time
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'evoting.settings')
django.setup()

from django.utils import timezone
from bot.models import Election

def update_election_statuses():
    """Update election statuses based on current time"""
    print("🕒 Updating Election Statuses")
    print("=" * 30)
    
    now = timezone.now()
    elections = Election.objects.all()
    
    updated_count = 0
    
    for election in elections:
        old_status = election.status
        
        # Determine new status based on time
        if now < election.start_time:
            new_status = 'pending'
        elif election.start_time <= now <= election.end_time:
            new_status = 'active'
        else:
            new_status = 'ended'
        
        # Update if status changed
        if old_status != new_status:
            election.status = new_status
            election.save()
            updated_count += 1
            print(f"✅ {election.title}: {old_status} → {new_status}")
        else:
            print(f"ℹ️ {election.title}: {old_status} (no change)")
    
    print(f"\n📊 Summary: {updated_count} elections updated")
    return updated_count

def show_election_summary():
    """Show summary of all elections"""
    print("\n📋 Election Summary")
    print("=" * 30)
    
    elections = Election.objects.all()
    now = timezone.now()
    
    for election in elections:
        print(f"\n🗳️ {election.title}")
        print(f"   Status: {election.status}")
        print(f"   Start: {election.start_time}")
        print(f"   End: {election.end_time}")
        print(f"   Current time: {now}")
        
        # Show time remaining or elapsed
        if election.status == 'pending':
            time_to_start = election.start_time - now
            print(f"   ⏰ Starts in: {time_to_start}")
        elif election.status == 'active':
            time_to_end = election.end_time - now
            print(f"   ⏰ Ends in: {time_to_end}")
        else:
            time_since_end = now - election.end_time
            print(f"   ⏰ Ended: {time_since_end} ago")
        
        # Show vote count
        total_votes = election.vote_set.count()
        print(f"   📊 Total votes: {total_votes}")

if __name__ == '__main__':
    update_election_statuses()
    show_election_summary()
