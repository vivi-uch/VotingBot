#!/usr/bin/env python
"""
Get detailed election results
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'evoting.settings')
django.setup()

from django.utils import timezone
from django.db.models import Count
from bot.models import Election, Candidate, Vote

def get_election_results(election_id=None):
    """Get results for specific election or all ended elections"""
    print("📊 Election Results")
    print("=" * 30)
    
    if election_id:
        elections = Election.objects.filter(id=election_id)
    else:
        elections = Election.objects.filter(status='ended')
    
    if not elections.exists():
        print("❌ No ended elections found")
        return
    
    for election in elections:
        print(f"\n🗳️ {election.title}")
        print(f"   Status: {election.status}")
        print(f"   Period: {election.start_time} to {election.end_time}")
        
        # Get all positions in this election
        positions = election.candidates.values_list('position', flat=True).distinct()
        
        total_voters = 0
        
        for position in positions:
            print(f"\n📍 {position}")
            print("-" * 20)
            
            # Get candidates for this position with vote counts
            candidates = election.candidates.filter(position=position).annotate(
                vote_count=Count('vote')
            ).order_by('-vote_count')
            
            position_total_votes = sum(c.vote_count for c in candidates)
            total_voters = max(total_voters, position_total_votes)
            
            if candidates:
                for i, candidate in enumerate(candidates, 1):
                    percentage = (candidate.vote_count / position_total_votes * 100) if position_total_votes > 0 else 0
                    winner_mark = "🏆" if i == 1 and candidate.vote_count > 0 else "  "
                    print(f"{winner_mark} {candidate.name}: {candidate.vote_count} votes ({percentage:.1f}%)")
            else:
                print("   No candidates")
        
        print(f"\n📈 Election Summary:")
        print(f"   Total unique voters: {total_voters}")
        print(f"   Total positions: {len(positions)}")
        print(f"   Total candidates: {election.candidates.count()}")

def get_detailed_vote_breakdown(election_id):
    """Get detailed vote breakdown for an election"""
    try:
        election = Election.objects.get(id=election_id)
        print(f"\n🔍 Detailed Breakdown: {election.title}")
        print("=" * 50)
        
        votes = Vote.objects.filter(election=election).select_related('candidate', 'matric_number')
        
        print(f"Individual votes ({votes.count()} total):")
        for vote in votes:
            print(f"  • {vote.matric_number.matric_number} → {vote.candidate.name} ({vote.candidate.position})")
            print(f"    Time: {vote.timestamp}")
            print(f"    Hash: {vote.vote_hash[:16]}...")
            print()
        
    except Election.DoesNotExist:
        print("❌ Election not found")

if __name__ == '__main__':
    # Update statuses first
    from update_election_status import update_election_statuses
    update_election_statuses()
    
    # Show results
    get_election_results()
    
    # Ask for detailed breakdown
    elections = Election.objects.all()
    if elections.exists():
        print(f"\nAvailable elections:")
        for election in elections:
            print(f"  {election.id}: {election.title} ({election.status})")
        
        election_id = input(f"\nEnter election ID for detailed breakdown (or press Enter to skip): ").strip()
        if election_id:
            get_detailed_vote_breakdown(election_id)
