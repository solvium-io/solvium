"""
Solvium Python SDK

A Python library for solving various types of captchas using the Solvium.io API service.
Supports Turnstile, reCAPTCHA v3, Cloudflare clearance, Vercel challenges, and more.
"""

from .client import Solvium, TaskRejected, TaskStatus

__version__ = "1.0.0"
__license__ = "Apache"
__description__ = "Python SDK for Solvium"

__all__ = [
    "Solvium",
    "TaskRejected",
    "TaskStatus",
]
