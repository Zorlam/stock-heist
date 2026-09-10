"""
Single place responsible for loading .env into the process environment.

Import this module (for its side effect) from anywhere that reads
os.environ for configuration — app/factory.py and
app/services/minimax_client.py both do. That way .env is guaranteed to
be loaded before any environment variable is read, regardless of which
module happens to get imported first (the app factory, a standalone
script, a test file run directly, etc.) — nothing has to remember to
call load_dotenv() itself, and calling it more than once is harmless
(python-dotenv is idempotent by default: it won't override a variable
that's already set in the environment).
"""

from dotenv import load_dotenv

load_dotenv()