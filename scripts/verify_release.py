"""Refuse inconsistent versions, sync conflicts and source/binary drift."""
import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(paths):
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file() and "__pycache__" not in p.parts}


def source_state():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    init = (ROOT / "src/acmais_link/__init__.py").read_text(encoding="utf-8")
    markup = (ROOT / "src/acmais_link/web/index.html").read_text(encoding="utf-8")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or f'__version__ = "{version}"' not in init:
        raise ValueError("Versões do projeto e do aplicativo divergentes.")
    if f"app.js?v={version}" not in markup or f"style.css?v={version}" not in markup:
        raise ValueError("A interface não corresponde à versão do aplicativo.")
    files = []
    for folder in ("src/acmais_link", "scripts", "installer", "tests"):
        for p in (ROOT / folder).rglob("*"):
            if "__pycache__" in p.parts:
                continue
            if re.search(r"-(?:COMP\d+|DESKTOP-[A-Z0-9]+|LAPTOP-[A-Z0-9]+)\.", p.name, re.I):
                raise ValueError(f"Cópia de conflito de sincronização: {p.relative_to(ROOT)}")
            files.append(p)
    files += [ROOT / p for p in ("pyproject.toml", "launcher.py", "ACMAIS_LINK.spec", "requirements-build.txt")]
    return {"version": version, "sources": fingerprint(files)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "record", "verify"))
    args = parser.parse_args()
    state = source_state()
    version = state["version"]
    snapshot = ROOT / f"build-v{version}/source-snapshot.json"
    manifest = ROOT / f"release-v{version}/source-manifest.json"
    if args.mode == "snapshot":
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(state, indent=2), encoding="utf-8")
    elif args.mode == "record":
        if json.loads(snapshot.read_text(encoding="utf-8")) != state:
            raise ValueError("O código mudou durante a compilação. Gere novamente.")
        bundle = ROOT / f"release-v{version}/ACMAIS LINK"
        if not (bundle / "ACMAIS LINK.exe").is_file():
            raise ValueError("Executável ausente.")
        state["bundle"] = fingerprint(bundle.rglob("*"))
        manifest.write_text(json.dumps(state, indent=2), encoding="utf-8")
    else:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        bundle = recorded.pop("bundle")
        if recorded != state or fingerprint((ROOT / f"release-v{version}/ACMAIS LINK").rglob("*")) != bundle:
            raise ValueError("O código ou o executável mudou após a compilação. Gere novamente antes de empacotar.")
    print(f"Consistência {args.mode}: {version} OK")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(f"Lançamento bloqueado: {error}", file=sys.stderr)
        sys.exit(1)
