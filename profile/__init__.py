"""Profile management package for SahayAI.

Provides citizen profile persistence, profile management, and scheme eligibility matching.
"""

from .database import Database
from .profile_manager import ProfileManager
from .account_manager import AccountManager
from .auth_service import AuthService
from .session_manager import SessionManager

__all__ = [
    "Database",
    "ProfileManager",
    "AccountManager",
    "AuthService",
    "SessionManager",
]

# Backward-compatibility fallback for Python standard library 'profile' module:
# When standard library tools (e.g. cProfile, torch.distributed) execute `import profile`,
# Python resolves this directory if cwd is at the root of sys.path.
# We bind stdlib profile symbols so internal tooling continues to function without naming conflicts.
_stdlib_profile = None
try:
    import sys, importlib.util, importlib.machinery
    for _p in sys.path:
        if _p and _p not in ('.', ''):
            try:
                _spec = importlib.machinery.PathFinder.find_spec('profile', [_p])
                if _spec and _spec.origin and _spec.origin.endswith('profile.py'):
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    _stdlib_profile = _mod
                    break
            except Exception:
                continue
    if _stdlib_profile is not None:
        run = getattr(_stdlib_profile, 'run', None)
        runctx = getattr(_stdlib_profile, 'runctx', None)
        Profile = getattr(_stdlib_profile, 'Profile', None)
except Exception:
    pass


def __getattr__(name):
    global _stdlib_profile
    if _stdlib_profile is not None and hasattr(_stdlib_profile, name):
        return getattr(_stdlib_profile, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


