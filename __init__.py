"""
WordBank Generator - Unified Web Application

A comprehensive web-based tool for speech therapists and translators to:
1. GENERATE wordbanks from scratch with intelligent data fetching
2. EDIT and review wordbank entries
3. TRANSLATE wordbanks to other languages

All data is fetched from external sources - no hardcoded fallbacks.
"""

from .config import VERSION

__version__ = VERSION
__all__ = ['app', 'VERSION']
