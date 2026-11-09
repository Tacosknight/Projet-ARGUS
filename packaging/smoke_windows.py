"""Recette HTTP de l'EXE Windows réel, sans import des sources applicatives.

À lancer depuis le checkout de confiance, jamais depuis un dossier téléchargé.
Ce test n'affirme pas bloquer le réseau : la recette VM hors ligne reste requise.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from uuid import uuid4


def get_json(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)


def upload(url, image):
    boundary = uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test.png\"\r\n"
            "Content-Type: image/png\r\n\r\n").encode() + image.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Échec HTTP {exc.code} de la recette OCR : {detail}") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    # Génération d'un échantillon sans données sensibles, avec le Python de recette.
    from PIL import Image, ImageDraw, ImageFont
    with tempfile.TemporaryDirectory(prefix="ARGUS recette été ") as directory:
        root = Path(directory)
        image = Image.new("RGB", (1800, 800), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "arial.ttf"), 64)
        for position, line in enumerate(("FACTURE ARGUS TEST 12345", "TOTAL TTC 120.00 EUR", "DATE 09/11/2026")):
            draw.text((100, 100 + position * 160), line, font=font, fill="black")
        fixture = root / "facture été.png"
        image.save(fixture)
        environment = dict(os.environ, ARGUS_DATA_DIR=str(root / "data"),
                           PADDLE_HOME=str(root / "paddle"), PADDLE_PDX_CACHE_HOME=str(root / "paddlex"))
        # Éviter qu'un chemin de développement court-circuite les modèles embarqués.
        environment.pop("ARGUS_MODELS_DIR", None)
        environment.pop("PYTHONPATH", None)
        process = subprocess.Popen([str(executable), "--no-browser"], env=environment, cwd=root)
        try:
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"L'EXE s'est arrêté avant le démarrage ({process.returncode}).")
                try:
                    get_json("http://127.0.0.1:8000/health")
                    break
                except (urllib.error.URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Démarrage de l'EXE trop long.")
                    time.sleep(0.5)
            with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=10) as response:
                if b"readApiResponse" not in response.read():
                    raise RuntimeError("L'interface complète est absente du paquet.")
            result = upload("http://127.0.0.1:8000/api/scan", fixture)
            text = result.get("raw_text", "").upper()
            if "FACTURE" not in text or "12345" not in text:
                raise RuntimeError("L'inférence réelle n'a pas reconnu le texte de recette.")
            with urllib.request.urlopen("http://127.0.0.1:8000/api/export", timeout=30) as response:
                if not response.read().startswith(b"PK"):
                    raise RuntimeError("Export Excel invalide.")
            print("EXE : interface, OCR réel et export validés. Réseau non bloqué par ce test.")
        except Exception:
            log_path = root / "data" / "logs" / "argus.log"
            if log_path.is_file():
                print("Journal technique de l'échantillon synthétique :")
                print(log_path.read_text(encoding="utf-8", errors="replace"))
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
