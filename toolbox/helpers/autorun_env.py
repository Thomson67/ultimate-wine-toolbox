"""Edit per-game compatibility variables without duplicating ENV lines."""
import argparse
from pathlib import Path
import shlex

KEY = 'UMU_DIRECT_GAME'

def env_tokens(text):
    return [token for line in text.splitlines() if line.startswith('ENV=')
            for token in shlex.split(line[4:])]

def enabled(text, key=KEY):
    values = [token.split('=', 1)[1] for token in env_tokens(text)
              if token.startswith(key + '=')]
    return bool(values and values[-1] == '1')

def rewrite(text, enable, key=KEY):
    tokens = [token for token in env_tokens(text) if not token.startswith(key + '=')]
    if enable:
        tokens.append(key + '=1')
    elif key != KEY:
        tokens.append(key + '=0')
    lines = [line for line in text.splitlines() if not line.startswith('ENV=')]
    if tokens:
        lines.append('ENV=' + shlex.join(tokens))
    return '\n'.join(lines) + '\n'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['get', 'set', 'copy'])
    parser.add_argument('path', type=Path)
    parser.add_argument('value', nargs='?')
    parser.add_argument('--key', choices=[KEY, 'PROTON_SONY_HIDRAW_XINPUT'], default=KEY)
    args = parser.parse_args()
    text = args.path.read_text()
    if args.action == 'get':
        print(int(enabled(text, args.key)) if args.key == KEY else next((token.split('=', 1)[1] for token in reversed(env_tokens(text)) if token.startswith(args.key + '=')), 'inherit'))
        return
    if args.action == 'copy':
        destination = Path(args.value)
        tokens = env_tokens(text)
        result = destination.read_text()
        if tokens:
            result += 'ENV=' + shlex.join(tokens) + '\n'
        destination.write_text(result)
        return
    if args.value not in ('0', '1', 'inherit'):
        parser.error('set requires 0, 1 or inherit')
    if args.value == 'inherit':
        tokens = [token for token in env_tokens(text) if not token.startswith(args.key + '=')]
        lines = [line for line in text.splitlines() if not line.startswith('ENV=')]
        if tokens:
            lines.append('ENV=' + shlex.join(tokens))
        result = '\n'.join(lines) + '\n'
    else:
        result = rewrite(text, args.value == '1', args.key)
    temp = args.path.with_name(args.path.name + '.uwt-env-tmp')
    temp.write_text(result)
    temp.replace(args.path)

if __name__ == '__main__':
    main()
