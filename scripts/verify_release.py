"""Refuse inconsistent versions, sync conflicts and source/binary drift."""
import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

from acmais_link import __version__
from acmais_link.web_home import home_filename, render_home

ROOT = Path(__file__).resolve().parents[1]
HOME_TEMPLATE = ROOT / "src/acmais_link/web/index.html"


def fingerprint(paths):
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file() and "__pycache__" not in p.parts}


def source_state():
    version = __version__
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){2}", version) or any(
        int(part) > 65535 for part in version.split(".")
    ):
        raise ValueError("Use três números de versão válidos para o Windows.")
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if ("version" in metadata["project"] or "version" not in metadata["project"].get("dynamic", ())
            or metadata["tool"]["setuptools"]["dynamic"]["version"]["attr"] != "acmais_link.__version__"):
        raise ValueError("A versão do pacote deve ser lida de acmais_link.__version__.")
    render_home(HOME_TEMPLATE.read_text(encoding="utf-8"))
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


def verify_bundled_home(bundle):
    web = bundle / "_internal" / "web"
    expected_name = home_filename()
    if {page.name for page in web.glob("index*.html")} != {expected_name}:
        raise ValueError("O pacote precisa conter apenas a página inicial desta versão.")
    expected = render_home(HOME_TEMPLATE.read_text(encoding="utf-8"))
    if (web / expected_name).read_text(encoding="utf-8") != expected:
        raise ValueError("O rodapé ou os recursos da página empacotada ficaram fora de sincronia.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("snapshot", "record", "verify"))
    args = parser.parse_args()
    state = source_state()
    version = state["version"]
    snapshot = ROOT / f"build-v{version}/source-snapshot.json"
    manifest = ROOT / f"release-v{version}/source-manifest.json"
    bundle_dir = ROOT / f"release-v{version}/ACMAIS LINK"
    if args.mode == "snapshot":
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(state, indent=2), encoding="utf-8")
    elif args.mode == "record":
        if json.loads(snapshot.read_text(encoding="utf-8")) != state:
            raise ValueError("O código mudou durante a compilação. Gere novamente.")
        if not (bundle_dir / "ACMAIS LINK.exe").is_file():
            raise ValueError("Executável ausente.")
        verify_bundled_home(bundle_dir)
        state["bundle"] = fingerprint(bundle_dir.rglob("*"))
        manifest.write_text(json.dumps(state, indent=2), encoding="utf-8")
    else:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        bundle = recorded.pop("bundle")
        verify_bundled_home(bundle_dir)
        if recorded != state or fingerprint(bundle_dir.rglob("*")) != bundle:
            raise ValueError("O código ou o executável mudou após a compilação. Gere novamente antes de empacotar.")
    print(f"Consistência {args.mode}: {version} OK")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print(f"Lançamento bloqueado: {error}", file=sys.stderr)
        sys.exit(1)
