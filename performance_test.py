#!/usr/bin/env python3
"""
Simple Performance Test Script
Measures face verification and vote storage timing
"""

import os
import sys
import time
import django
from datetime import datetime

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'evoting.settings')
django.setup()

from bot.models import Voter, Election, Candidate, Vote
from bot.services.face_recognition import FaceRecognizer
from django.utils import timezone
import hashlib

class SimplePerformanceTest:
    def __init__(self):
        self.results = []
        print("🚀 Starting Performance Tests...")
        print("=" * 50)
    
    def log_result(self, test_name, duration, success, details=""):
        """Log a test result"""
        result = {
            'test': test_name,
            'time': round(duration, 3),
            'success': success,
            'details': details,
            'timestamp': datetime.now().strftime('%H:%M:%S')
        }
        self.results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}: {duration:.3f}s {details}")
    
    def test_face_verification(self):
        """Test face verification performance"""
        print("\n🔍 Testing Face Verification...")
        
        try:
            # Test 1: Initialize Face Recognizer
            start_time = time.time()
            face_recognizer = FaceRecognizer()
            init_time = time.time() - start_time
            self.log_result("Face Recognizer Init", init_time, True)
            
            # Test 2: Load test image (if exists)
            test_image_path = "test_images/test_face.jpg"
            if os.path.exists(test_image_path):
                start_time = time.time()
                result = face_recognizer.verify_voter(test_image_path)
                verify_time = time.time() - start_time
                self.log_result("Face Verification", verify_time, result is not None, 
                              f"- Result: {result}")
            else:
                print("⚠️  No test image found at test_images/test_face.jpg")
                print("   Create test_images folder and add test_face.jpg to test verification")
        
        except Exception as e:
            self.log_result("Face Verification", 0, False, f"Error: {str(e)}")
    
    def test_vote_storage(self):
        """Test vote storage performance"""
        print("\n🗳️  Testing Vote Storage...")
        
        try:
            # Create test data if needed
            voter, _ = Voter.objects.get_or_create(matric_number="TEST001")
            election, _ = Election.objects.get_or_create(
                title="Performance Test Election",
                defaults={
                    'start_time': timezone.now(),
                    'end_time': timezone.now() + timezone.timedelta(hours=1)
                }
            )
            candidate, _ = Candidate.objects.get_or_create(
                name="Test Candidate",
                position="Test Position",
                election=election
            )
            
            # Test 1: Single Vote Storage
            start_time = time.time()
            
            # Generate vote hash
            vote_string = f"TEST001:{candidate.id}:{election.id}:{timezone.now().isoformat()}"
            vote_hash = hashlib.sha256(vote_string.encode()).hexdigest()
            
            # Create vote
            vote = Vote.objects.create(
                matric_number=voter,
                candidate=candidate,
                election=election,
                vote_hash=vote_hash,
                timestamp=timezone.now()
            )
            
            storage_time = time.time() - start_time
            self.log_result("Single Vote Storage", storage_time, True, 
                          f"- Vote ID: {str(vote.id)[:8]}...")
            
            # Test 2: Vote Verification Check
            start_time = time.time()
            has_voted = Vote.objects.filter(
                matric_number=voter,
                election=election
            ).exists()
            check_time = time.time() - start_time
            self.log_result("Vote Check Query", check_time, has_voted, 
                          f"- Has voted: {has_voted}")
            
            # Test 3: Vote Counting
            start_time = time.time()
            vote_count = Vote.objects.filter(candidate=candidate).count()
            count_time = time.time() - start_time
            self.log_result("Vote Count Query", count_time, True, 
                          f"- Total votes: {vote_count}")
            
            # Clean up test vote
            vote.delete()
            
        except Exception as e:
            self.log_result("Vote Storage", 0, False, f"Error: {str(e)}")
    
    def test_database_operations(self):
        """Test basic database operations"""
        print("\n💾 Testing Database Operations...")
        
        try:
            # Test 1: Voter Lookup
            start_time = time.time()
            voter_exists = Voter.objects.filter(matric_number="TEST001").exists()
            lookup_time = time.time() - start_time
            self.log_result("Voter Lookup", lookup_time, True, 
                          f"- Exists: {voter_exists}")
            
            # Test 2: Election List
            start_time = time.time()
            elections = list(Election.objects.all()[:10])
            list_time = time.time() - start_time
            self.log_result("Election List Query", list_time, True, 
                          f"- Found: {len(elections)} elections")
            
            # Test 3: Candidate List
            start_time = time.time()
            candidates = list(Candidate.objects.all()[:10])
            candidate_time = time.time() - start_time
            self.log_result("Candidate List Query", candidate_time, True, 
                          f"- Found: {len(candidates)} candidates")
            
        except Exception as e:
            self.log_result("Database Operations", 0, False, f"Error: {str(e)}")
    
    def show_summary(self):
        """Show test summary"""
        print("\n" + "=" * 50)
        print("📊 PERFORMANCE TEST SUMMARY")
        print("=" * 50)
        
        if not self.results:
            print("❌ No test results to show")
            return
        
        # Group results by category
        verification_tests = [r for r in self.results if 'Face' in r['test']]
        vote_tests = [r for r in self.results if 'Vote' in r['test']]
        db_tests = [r for r in self.results if 'Query' in r['test'] or 'Lookup' in r['test']]
        
        def show_category(name, tests):
            if not tests:
                return
            
            print(f"\n{name}:")
            total_time = sum(t['time'] for t in tests)
            passed = sum(1 for t in tests if t['success'])
            
            for test in tests:
                status = "✅" if test['success'] else "❌"
                print(f"  {status} {test['test']}: {test['time']:.3f}s")
            
            print(f"  📊 Total: {total_time:.3f}s | Passed: {passed}/{len(tests)}")
        
        show_category("🔍 Face Verification", verification_tests)
        show_category("🗳️  Vote Storage", vote_tests)
        show_category("💾 Database Operations", db_tests)
        
        # Overall stats
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r['success'])
        total_time = sum(r['time'] for r in self.results)
        
        print(f"\n🎯 OVERALL RESULTS:")
        print(f"   Tests: {passed_tests}/{total_tests} passed")
        print(f"   Total Time: {total_time:.3f}s")
        print(f"   Average: {total_time/total_tests:.3f}s per test")
        
        # Performance recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        slow_tests = [r for r in self.results if r['time'] > 1.0]
        if slow_tests:
            print("   ⚠️  Slow operations (>1.0s):")
            for test in slow_tests:
                print(f"      - {test['test']}: {test['time']:.3f}s")
        else:
            print("   ✅ All operations are fast (<1.0s)")
        
        # Save results to file
        self.save_results()
    
    def save_results(self):
        """Save results to a simple log file"""
        try:
            with open('performance_results.txt', 'w') as f:
                f.write(f"Performance Test Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 60 + "\n\n")
                
                for result in self.results:
                    status = "PASS" if result['success'] else "FAIL"
                    f.write(f"{result['timestamp']} | {status} | {result['test']} | {result['time']:.3f}s | {result['details']}\n")
                
                f.write(f"\nTotal Tests: {len(self.results)}\n")
                f.write(f"Passed: {sum(1 for r in self.results if r['success'])}\n")
                f.write(f"Total Time: {sum(r['time'] for r in self.results):.3f}s\n")
            
            print(f"\n💾 Results saved to: performance_results.txt")
            
        except Exception as e:
            print(f"⚠️  Could not save results: {e}")
    
    def run_all_tests(self):
        """Run all performance tests"""
        start_time = time.time()
        
        self.test_face_verification()
        self.test_vote_storage()
        self.test_database_operations()
        
        total_time = time.time() - start_time
        print(f"\n⏱️  Total test time: {total_time:.3f}s")
        
        self.show_summary()

def main():
    """Main function"""
    print("🎯 Simple E-Voting Performance Test")
    print("This script measures face verification and vote storage performance")
    print()
    
    try:
        tester = SimplePerformanceTest()
        tester.run_all_tests()
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
