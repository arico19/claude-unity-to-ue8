"""Doble clic: abre la aplicación de conversión Unity -> Unreal Engine 5.8."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unity2ue.gui import main  # noqa: E402

main()
