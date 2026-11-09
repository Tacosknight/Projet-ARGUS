"""Sérialisation des accès aux données du serveur mono-processus ARGUS."""

from threading import RLock

# Réentrant : les routes verrouillées appellent elles-mêmes SQLite/le cache.
# Ce verrou ne coordonne pas plusieurs instances/processus indépendants.
DATA_LOCK = RLock()
