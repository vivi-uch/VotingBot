#!/usr/bin/env python
"""
Script to create admin users
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'evoting.settings')
django.setup()

from bot.models import Admin

def main():
    print("👤 Admin Creation Script")
    print("=" * 30)
    
    telegram_id = input("Enter your Telegram ID: ").strip()
    
    if not telegram_id:
        print("Telegram ID cannot be empty")
        return
    
    if not telegram_id.isdigit():
        print("Telegram ID should be a number")
        return
    
    try:
        admin, created = Admin.objects.get_or_create(telegram_id=telegram_id)
        
        if created:
            print(f"Admin {telegram_id} created successfully!")
        else:
            print(f"Admin {telegram_id} already exists")
        
        admins = Admin.objects.all()
        print(f"\nCurrent admins ({admins.count()}):")
        for admin in admins:
            print(f"  • {admin.telegram_id}")
        
        print(f"\nYou can now use /admin in the Telegram bot!")
    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
