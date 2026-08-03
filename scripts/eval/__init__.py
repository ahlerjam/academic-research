"""Manuelle, nicht-hermetische Eval-Skripte (kein pytest-Discovery-Ziel).

Als regulaeres Package importierbar, damit Tests unter ``tests/`` die
Konfiguration einzelner Skripte (z.B. ``recall_at_k_model_ab.py``) ohne
zusaetzliches ``sys.path.insert`` pruefen koennen -- ``REPO_ROOT`` liegt
bereits ueber ``tests/conftest.py`` auf ``sys.path``.
"""
