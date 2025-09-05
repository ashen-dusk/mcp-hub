from __future__ import annotations

from typing import Optional, Tuple
from django.contrib.auth.models import User
from django.db import transaction
from .google import GoogleUserInfo


class UserService:
    """Service for managing user registration and authentication."""
    
    @staticmethod
    def _split_name(full_name: str) -> Tuple[str, str]:
        """Split a full name into first and last name."""
        if not full_name:
            return '', ''
        
        parts = full_name.strip().split()
        if len(parts) == 0:
            return '', ''
        elif len(parts) == 1:
            return parts[0], ''
        else:
            return parts[0], ' '.join(parts[1:])
    
    @staticmethod
    def get_or_create_user_from_google(google_info: GoogleUserInfo) -> Tuple[User, bool]:
        """
        Get or create a Django User from Google OAuth info.
        
        Returns:
            Tuple of (User, created) where created is True if user was just created.
        """
        with transaction.atomic():
            try:
                user = User.objects.get(email=google_info.email)
                created = False
                
                full_name = google_info.name or ''
                first_name, last_name = UserService._split_name(full_name)
                if user.first_name != first_name or user.last_name != last_name:
                    user.first_name = first_name
                    user.last_name = last_name
                    user.save()
                
                return user, created
                
            except User.DoesNotExist:
                username = google_info.email.split('@')[0]
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1
                
                full_name = google_info.name or ''
                first_name, last_name = UserService._split_name(full_name)
                
                user = User.objects.create_user(
                    username=username,
                    email=google_info.email,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=True
                )
                
                return user, True
