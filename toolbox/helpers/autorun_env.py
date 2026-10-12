"""Edit the opt-in UMU path setting without duplicating ENV lines."""
import argparse
from pathlib import Path
import shlex

KEY = 'UMU_DIRECT_GAME'

def env_tokens(text):
    return [token for line in text.splitlines() if line.startswith('ENV=')
            for token in shlex.split(line[4:])]

def enabled(text):
    values = [token.split('=', 1)[1] for token in env_tokens(text)
              if token.startswith(KEY + '=')]
    return bool(values and values[-1] == '1')

def rewrite(text, enable):
    tokens = [token for token in env_tokens(text) if not token.startswith(KEY + '=')]
    if enable:
        tokens.append(KEY + '=1')
    lines = [line for line in text.splitlines() if not line.startswith('ENV=')]
    if tokens:
        lines.append('ENV=' + shlex.join(tokens))
    return '\n'.join(lines) + '\n'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['get', 'set', 'copy'])
    parser.add_argument('path', type=Path)
    parser.add_argument('value', nargs='?')
    args = parser.parse_args()
    text = args.path.read_text()
    if args.action == 'get':
        print(int(enabled(text)))
        return
    if args.action == 'copy':
        destination = Path(args.value)
        tokens = env_tokens(text)
        result = destination.read_text()
        if tokens:
            result += 'ENV=' + shlex.join(tokens) + '\n'
        destination.write_text(result)
        return
    if args.value not in ('0', '1'):
        parser.error('set requires 0 or 1')
    result = rewrite(text, args.value == '1')
    temp = args.path.with_name(args.path.name + '.uwt-env-tmp')
    temp.write_text(result)
    temp.replace(args.path)

if __name__ == '__main__':
    main()
