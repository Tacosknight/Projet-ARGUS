#!/usr/bin/env python3
"""
Lanceur du serveur Web Mobile Facture-Checker.
Détecte automatiquement l'adresse IP Wi-Fi locale et génère un QR code
dans le terminal pour permettre une connexion instantanée depuis un smartphone.
"""

from pathlib import Path
import socket
import sys
import uvicorn
import qrcode

# Chemin racine
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def get_local_ip() -> str:
    """Récupère l'adresse IP locale de la machine sur le réseau local (Wi-Fi/Ethernet)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connexion fictive pour déterminer l'interface réseau active
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def print_startup_banner(ip: str, port: int) -> None:
    """Affiche la bannière de démarrage avec le QR code scannable par mobile."""
    url = f"http://{ip}:{port}"
    local_url = f"http://localhost:{port}"

    print("\n" + "=" * 65)
    print("       FACTURE-CHECKER : SCANNER & AUDIT MOBILE       ")
    print("=" * 65)
    print(f"\n📱 Accès depuis votre smartphone sur le même Wi-Fi :")
    print(f"   👉 \033[1m\033[96m{url}\033[0m\n")
    print(f"💻 Accès depuis cet ordinateur :")
    print(f"   👉 \033[94m{local_url}\033[0m\n")

    print("📷 Scannez ce QR Code avec l'appareil photo de votre smartphone :")
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    print("\nAppuyez sur Ctrl+C pour arrêter le serveur.\n")


def main() -> None:
    port = 8000
    ip = get_local_ip()
    print_startup_banner(ip, port)

    # Lancement du serveur uvicorn
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=True,
    )


if __name__ == "__main__":
    main()
