#!/usr/bin/env python3
"""
Lanceur du serveur Web Mobile Facture-Checker.
Détecte automatiquement l'adresse IP Wi-Fi locale et génère un QR code
dans le terminal pour permettre une connexion instantanée depuis un smartphone.
"""

from pathlib import Path
import argparse
import socket
import sys
import threading
import webbrowser
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


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serveur local ARGUS")
    parser.add_argument("--mobile", action="store_true", help="Autoriser le scanner smartphone sur le réseau local.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    import os
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    port = args.port
    ip = get_local_ip() if args.mobile else "127.0.0.1"
    if args.mobile:
        print_startup_banner(ip, port)
    else:
        print(f"\nARGUS est disponible sur http://127.0.0.1:{port}")
        print("Mode local sécurisé actif. Utilisez --mobile pour le scanner smartphone.\n")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

    # Lancement du serveur uvicorn
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0" if args.mobile else "127.0.0.1",
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
