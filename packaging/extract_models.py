"""Extraire uniquement les données des modèles dans un dossier neuf, sans code."""
import argparse
from pathlib import Path, PurePosixPath
import shutil
import zipfile


def extract(archive_path: Path, destination: Path) -> None:
    if not destination.is_dir() or any(destination.iterdir()):
        raise ValueError("La destination doit être un dossier vide existant.")
    allowed = {"inference.yml", "inference.json", "inference.pdmodel", "inference.pdiparams"}
    roles = {"text_detection", "text_recognition", "textline_orientation"}
    with zipfile.ZipFile(archive_path) as archive:
        selected = []
        seen = set()
        total = 0
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if member.is_dir():
                continue
            parts = path.parts[1:] if path.parts[:1] == ("models",) else path.parts
            if (len(parts) != 2 or parts[0] not in roles or parts[1] not in allowed
                    or "\\" in member.filename or path.is_absolute()):
                raise ValueError(f"Fichier inattendu : {member.filename}")
            if parts in seen:
                raise ValueError("Fichier dupliqué.")
            seen.add(parts)
            total += member.file_size
            if total > 4 * 1024 ** 3:
                raise ValueError("Archive trop volumineuse.")
            selected.append((member, parts))
        for member, parts in selected:
            target = destination.joinpath(*parts)
            target.parent.mkdir(exist_ok=True)
            with archive.open(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    extract(args.archive, args.destination)
