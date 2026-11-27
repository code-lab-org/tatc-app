"""
TAT-C application.

Settings are environment variables, which may also be set in a `.env` file
(see the README): it is loaded once, here, before any module of the package
reads them. Variables already set in the environment take precedence.
"""

from dotenv import load_dotenv

load_dotenv()

__version__ = "2.2.0"
