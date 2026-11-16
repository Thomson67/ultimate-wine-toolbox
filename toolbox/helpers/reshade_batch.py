"""Identify a single literal game executable in a simple Windows batch launcher."""
from pathlib import PurePosixPath
import re

from es_launcher import batch_path, script

# Keep quotes on the tokens: START consumes the first quoted argument as a title.
TOKEN = re.compile(r'"[^"]*"|[^\s"]+')
NON_LITERAL = re.compile(r'[:%!*?<>|&^"\r\n\t]')
SETUP = {'echo', 'echo.', 'rem', 'set', 'setlocal', 'endlocal', 'chcp', 'cls', 'pause'}
START_FLAGS = {'/wait', '/b', '/min', '/max', '/normal', '/i'}


def prefix_path(value, directory, batch_folder):
    path = value.strip('"').replace('\\', '/')
    if path.casefold().startswith('%~dp0'):
        path = str(batch_folder / path[5:].lstrip('/'))
    elif path.casefold().startswith('c:/'):
        path = 'drive_c/' + path[3:]
    elif not path.startswith('/'):
        path = str(directory / path)
    result = PurePosixPath(path)
    if result.is_absolute() or '..' in result.parts or NON_LITERAL.search(path):
        raise ValueError('Batch launcher uses a nonliteral or external path')
    return result


def start_target(args):
    while args and args[0].casefold() in START_FLAGS:
        args = args[1:]
    if args and args[0].startswith('"'):
        args = args[1:]
        while args and args[0].casefold() in START_FLAGS:
            args = args[1:]
    if not args:
        raise ValueError('Batch launcher has no explicit START target')
    return args[0]


def batch_executable(rom, autorun):
    batch = batch_path(autorun)
    directives = {key.strip().upper(): value.strip() for line in autorun.splitlines()
                  if '=' in line for key, value in (line.split('=', 1),)}
    root = PurePosixPath('.')
    directory = prefix_path(directives.get('DIR', '.'), root, batch.parent)
    targets = set()
    for line in script(rom, batch).splitlines():
        line = line.strip().removeprefix('@').lstrip()
        if not line or line.startswith('::'):
            continue
        args = TOKEN.findall(line)
        if line.count('"') % 2 or any(re.search(r'[&|<>^()]', token) for token in args if not token.startswith('"')):
            raise ValueError('Batch launcher has compound or redirected commands')
        command = args[0].casefold()
        if command in SETUP:
            continue
        if command in ('cd', 'chdir'):
            paths = args[2:] if args[1:2] and args[1].casefold() == '/d' else args[1:]
            if len(paths) != 1:
                raise ValueError('Batch launcher has an unresolved working directory')
            directory = prefix_path(paths[0], directory, batch.parent)
            continue
        if command == 'exit' and args[1:2] == ['/b']:
            break
        target = start_target(args[1:]) if command == 'start' else args[0]
        executable = prefix_path(target, directory, batch.parent)
        if executable.suffix.casefold() != '.exe':
            raise ValueError('Batch launcher does not name a single literal executable')
        targets.add(executable)
    if len(targets) != 1:
        raise ValueError('Batch launcher does not name a single literal executable')
    return targets.pop().as_posix()
