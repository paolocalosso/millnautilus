#!/usr/bin/env python3
"""Millnautilus - entry point."""
import sys
from millnautilus.app import MillnautilusApp

if __name__ == "__main__":
    sys.exit(MillnautilusApp().run(sys.argv))
