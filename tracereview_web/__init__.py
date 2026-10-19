"""Vercel entry-point package for the Django project in ``src/``."""

from pathlib import Path

_src_package = Path(__file__).resolve().parents[1] / "src" / "tracereview_web"
__path__.append(str(_src_package))
