#!/usr/bin/env python3
"""Reuse the active stream context without replacing distribution configuration."""
import argparse
import fnmatch
import glob
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path


TOKEN = re.compile(r'''\s+|\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[;{}]|(?:\\.|\$\{[^}]*\}|[^\s;{}'"\#\\])+''')


def remove_markers(text, prefix):
    include = re.escape(f"include {prefix.as_posix()}/stream.d/*.conf;")
    old = re.compile(
        r"(?m)^[ \t]*# Emby Edge managed stream include[ \t]*\n"
        r"[ \t]*stream\s*\{\s*" + include + r"\s*\}[ \t]*\n?"
    )
    managed = re.compile(
        r"(?m)^[ \t]*# Emby Edge managed stream begin\n"
        r"(?:[ \t]*stream\s*\{\n)?[ \t]*" + include + r"\n"
        r"(?:[ \t]*\}\n)?[ \t]*# Emby Edge managed stream end\n?"
    )
    return managed.sub("", old.sub("", text))


@dataclass
class Directive:
    words: list
    start: int
    end: int
    children: list | None = None
    closing: int | None = None


def parse(text):
    tokens = []
    offset = 0
    for match in TOKEN.finditer(text):
        if match.start() != offset:
            raise ValueError("Unsupported Nginx syntax; configuration left unchanged")
        offset = match.end()
        value = match.group()
        if not value.isspace() and not value.startswith("#"):
            tokens.append((value, match.start(), match.end()))
    if offset != len(text):
        raise ValueError("Unsupported Nginx syntax; configuration left unchanged")

    def block(index, nested=False):
        directives = []
        while index < len(tokens):
            if tokens[index][0] == "}":
                if not nested:
                    raise ValueError("Unexpected closing brace in Nginx configuration")
                return directives, index + 1, tokens[index][1]
            start = tokens[index][1]
            words = []
            while index < len(tokens) and tokens[index][0] not in (";", "{", "}"):
                words.append(tokens[index][0].strip("\"'"))
                index += 1
            if not words or index == len(tokens) or tokens[index][0] == "}":
                raise ValueError("Incomplete Nginx directive")
            if tokens[index][0] == "{":
                children, index, closing = block(index + 1, True)
                directives.append(Directive(words, start, tokens[index - 1][2], children, closing))
            else:
                directives.append(Directive(words, start, tokens[index][2]))
                index += 1
        if nested:
            raise ValueError("Unclosed Nginx block")
        return directives, index, None

    return block(0)[0]


def plan(configuration, legacy_marker=False, remove=False):
    configuration = Path(configuration).resolve()
    prefix = configuration.parent
    sources = {}

    def load(path):
        path = Path(path).resolve()
        if path not in sources:
            original = path.read_text(encoding="utf-8")
            clean = remove_markers(original, prefix)
            if path == configuration and legacy_marker:
                # A previous installer also wrote this include directly in main context.
                for item in reversed(parse(clean)):
                    if item.words == ["include", f"{prefix.as_posix()}/stream.d/*.conf"] and item.children is None:
                        clean = clean[:item.start] + clean[item.end:]
            sources[path] = [original, clean]
        return path, parse(sources[path][1])

    def walk(path, directives, context=(), stack=()):
        if path in stack:
            raise ValueError("Recursive Nginx include; configuration left unchanged")
        for item in directives:
            yield path, item, context
            if item.words[0] == "include" and len(item.words) == 2:
                pattern = Path(item.words[1])
                if not pattern.is_absolute():
                    pattern = prefix / pattern
                for included in sorted(glob.glob(str(pattern))):
                    child_path, children = load(included)
                    yield from walk(child_path, children, context, stack + (path,))
            elif item.children is not None:
                # Nested blocks share their file; only include edges participate in cycle checks.
                yield from walk(path, item.children, context + (item.words[0],), stack)

    path, directives = load(configuration)
    expanded = list(walk(path, directives))
    if remove:
        return {path: clean for path, (original, clean) in sources.items() if clean != original}
    streams = [(path, item) for path, item, context in expanded if not context and item.words == ["stream"]]
    if len(streams) > 1:
        raise ValueError("Multiple unmanaged stream blocks found; merge them before installing Worker")

    target = str(prefix / "stream.d" / "emby.conf")
    covered = False
    for _, item, context in expanded:
        if context == ("stream",) and item.words[0] == "include" and len(item.words) == 2:
            pattern = Path(item.words[1])
            if not pattern.is_absolute():
                pattern = prefix / pattern
            if fnmatch.fnmatch(target, os.path.normpath(str(pattern))):
                covered = True
    if not covered:
        include = f"include {prefix.as_posix()}/stream.d/*.conf;"
        if streams:
            path, stream = streams[0]
            text = sources[path][1]
            gap = "" if text[:stream.closing].endswith("\n") else "\n"
            addition = (gap + "    # Emby Edge managed stream begin\n"
                        f"    {include}\n    # Emby Edge managed stream end\n")
            sources[path][1] = text[:stream.closing] + addition + text[stream.closing:]
        else:
            gap = "" if sources[configuration][1].endswith("\n") else "\n"
            sources[configuration][1] += (gap + "# Emby Edge managed stream begin\nstream {\n"
                                         f"    {include}\n}}\n# Emby Edge managed stream end\n")
    return {path: clean for path, (original, clean) in sources.items() if clean != original}


def write_changes(changes):
    for path, content in changes.items():
        stat = path.stat()
        fd, temporary = tempfile.mkstemp(prefix=".emby-nginx-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, stat.st_mode & 0o7777)
            if hasattr(os, "chown"):
                os.chown(temporary, stat.st_uid, stat.st_gid)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("configuration", nargs="?", default="/etc/nginx/nginx.conf")
    parser.add_argument("--legacy-marker", action="store_true")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    try:
        changes = plan(args.configuration, args.legacy_marker, args.remove)
        write_changes(changes)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Worker Nginx configuration failed: {error}\n")
    print("Worker stream configuration ready" if not args.remove else "Worker stream include removed")


if __name__ == "__main__":
    main()
