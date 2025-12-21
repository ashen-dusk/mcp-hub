from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Extended User model with role-based access control."""

    class Role(models.TextChoices):
        STAFF = 'staff', 'Staff'
        PUBLISHER = 'publisher', 'Publisher'
        USER = 'user', 'User'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.USER,
        help_text='User role for access control'
    )

    google_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text='Google OAuth user ID (sub claim)'
    )

    profile_picture = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text='User profile picture URL'
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Additional user metadata in JSON format'
    )

    class Meta:
        db_table = 'auth_user'
        verbose_name = 'user'
        verbose_name_plural = 'users'
 
    def __str__(self):
        return f"{self.email} ({self.role})"
