#!/usr/bin/env python3
"""
ollama2gguf.py - expose Ollama's model blobs as properly named .gguf files
for llama.cpp (llama-server, llama-cli, --models-dir, etc.).

Ollama stores models as content-addressed blobs (sha256-<hash>, no extension).
The manifests tell us which blob is the GGUF weights ("image.model") and which
is the vision projector ("image.projector"). This script reads the manifests
and creates links like:

    llama3.2-3b.gguf
    llava-7b.gguf
    llava-7b.mmproj.gguf        (vision projector, if present)

Hardlinks are used by default (no extra disk space, survive `ollama rm` of the
original name as long as the link exists). Hardlinks only work on the same
filesystem; use --symlink or --copy otherwise.

Usage:
    ./ollama2gguf.py /path/to/llama-models
    ./ollama2gguf.py /path/to/llama-models --dry-run
    ./ollama2gguf.py /path/to/llama-models --prune      # remove stale links
    ./ollama2gguf.py /path/to/llama-models --symlink
    ./ollama2gguf.py /path/to/llama-models --models-src /usr/share/ollama/.ollama/models
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

MEDIA_MODEL = "application/vnd.ollama.image.model"
MEDIA_PROJECTOR = "application/vnd.ollama.image.projector"
DEFAULT_REGISTRY = "registry.ollama.ai"


def find_models_dir(cli_value):
    """Locate the Ollama models directory (the one containing manifests/ and blobs/)."""
    candidates = []
    if cli_value:
        candidates.append(Path(cli_value))
    if os.environ.get("OLLAMA_MODELS"):
        candidates.append(Path(os.environ["OLLAMA_MODELS"]))
    home = Path.home()
    candidates += [
        home / ".ollama" / "models",                      # macOS / Linux user / Windows
        Path("/usr/share/ollama/.ollama/models"),         # Linux systemd service install
        Path("/var/lib/ollama/models"),                   # some distro packages
    ]
    for c in candidates:
        if (c / "manifests").is_dir() and (c / "blobs").is_dir():
            return c
    sys.exit(
        "Could not find the Ollama models directory. Tried:\n  "
        + "\n  ".join(str(c) for c in candidates)
        + "\nPass it with --models-src."
    )


def safe(s):
    """Make a string filesystem-friendly."""
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in s)


def model_name(manifest_path, manifests_root):
    """
    manifests/<host>/<namespace>/<model>/<tag>  ->  friendly base name.
      registry.ollama.ai/library/llama3.2/3b -> llama3.2-3b
      registry.ollama.ai/someuser/foo/latest -> someuser_foo-latest
      hf.co/bartowski/Foo-GGUF/Q4_K_M        -> hf.co_bartowski_Foo-GGUF-Q4_K_M
    """
    rel = manifest_path.relative_to(manifests_root).parts
    if len(rel) < 4:
        # unusual layout; fall back to joining everything
        return safe("-".join(rel))
    host, namespace, *model_parts, tag = rel
    model = "_".join(model_parts)
    if host == DEFAULT_REGISTRY:
        base = model if namespace == "library" else f"{namespace}_{model}"
    else:
        base = f"{host}_{namespace}_{model}"
    return safe(f"{base}-{tag}")


def blob_path(blobs_dir, digest):
    # digest looks like "sha256:abcd..."; on disk it's "sha256-abcd..."
    return blobs_dir / digest.replace(":", "-", 1)


def place(src, dst, mode, dry):
    """Create dst pointing at src. Returns a short status string."""
    if dst.exists() or dst.is_symlink():
        try:
            if mode == "symlink" and dst.is_symlink() and Path(os.readlink(dst)) == src:
                return "ok (already linked)"
            if mode != "symlink" and not dst.is_symlink() and os.path.samefile(src, dst):
                return "ok (already linked)"
        except OSError:
            pass
        if dry:
            return "would replace"
        dst.unlink()
    if dry:
        return "would link" if mode != "copy" else "would copy"
    if mode == "hardlink":
        try:
            os.link(src, dst)
            return "linked"
        except OSError as e:
            raise RuntimeError(
                f"hardlink failed ({e}). Different filesystem or permissions? "
                "Try --symlink or --copy."
            )
    if mode == "symlink":
        os.symlink(src, dst)
        return "symlinked"
    shutil.copy2(src, dst)
    return "copied"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dest", type=Path, help="directory llama.cpp reads GGUFs from")
    ap.add_argument("--models-src", help="Ollama models dir (default: auto-detect)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--symlink", action="store_true", help="use symlinks instead of hardlinks")
    mode.add_argument("--copy", action="store_true", help="copy files instead of linking")
    ap.add_argument("--no-mmproj", action="store_true", help="skip vision projector files")
    ap.add_argument("--prune", action="store_true",
                    help="remove .gguf links in dest that no longer match an Ollama model")
    ap.add_argument("--dry-run", "-n", action="store_true", help="show what would happen")
    args = ap.parse_args()

    link_mode = "symlink" if args.symlink else "copy" if args.copy else "hardlink"
    src_root = find_models_dir(args.models_src)
    manifests_root = src_root / "manifests"
    blobs_dir = src_root / "blobs"
    print(f"Ollama models: {src_root}")
    print(f"Destination:   {args.dest}  ({link_mode})\n")

    if not args.dry_run:
        args.dest.mkdir(parents=True, exist_ok=True)

    wanted = set()
    errors = 0

    for mf in sorted(p for p in manifests_root.rglob("*") if p.is_file()):
        try:
            data = json.loads(mf.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"! skipping unreadable manifest {mf}: {e}")
            continue

        base = model_name(mf, manifests_root)
        for layer in data.get("layers", []):
            mt = layer.get("mediaType")
            if mt == MEDIA_MODEL:
                fname = f"{base}.gguf"
            elif mt == MEDIA_PROJECTOR and not args.no_mmproj:
                fname = f"{base}.mmproj.gguf"
            else:
                continue

            src = blob_path(blobs_dir, layer["digest"])
            if not src.exists():
                print(f"! {fname}: blob missing ({src.name}) - partial download?")
                errors += 1
                continue

            dst = args.dest / fname
            wanted.add(fname)
            try:
                status = place(src, dst, link_mode, args.dry_run)
            except RuntimeError as e:
                print(f"! {fname}: {e}")
                errors += 1
                continue
            size_gb = src.stat().st_size / 1e9
            print(f"  {status:<20} {fname}  ({size_gb:.2f} GB)")

    if args.prune and args.dest.is_dir():
        for f in sorted(args.dest.glob("*.gguf")):
            if f.name in wanted:
                continue
            # only touch things that are links/copies of ollama blobs
            is_link = f.is_symlink()
            try:
                is_blob = is_link or f.stat().st_nlink > 1
            except OSError:
                is_blob = True
            if is_blob:
                print(f"  {'would prune' if args.dry_run else 'pruned':<20} {f.name}")
                if not args.dry_run:
                    f.unlink()
            else:
                print(f"  {'kept (not a link)':<20} {f.name}")

    print(f"\nDone. {len(wanted)} file(s) processed, {errors} problem(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
