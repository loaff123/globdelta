"""GlobDelta: strict root-gitignore proof-or-witness comparison."""
from .api import compare_policies, explain_path
from .budget import Limits
from .model import ParseResult, Report
from .parse import parse_policy

__version__ = '0.1.0'
__all__ = ['Limits', 'ParseResult', 'Report', 'compare_policies', 'explain_path', 'parse_policy']
