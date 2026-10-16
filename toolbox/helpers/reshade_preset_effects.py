"""Resolve preset effect filenames to the backend's known shader packs, offline."""
import configparser
import json
from pathlib import Path, PurePosixPath
import re

INDEX=Path(__file__).resolve().parents[1]/'data/reshade-effect-index.json'


def analyze(source, index=INDEX):
    from community_profiles import profile_bytes
    data=profile_bytes('reshade',Path(source).read_bytes())
    parser=configparser.ConfigParser(interpolation=None,strict=True)
    parser.read_string('[UWT_PRESET]\n'+data.decode('utf-8-sig'))
    packs=json.loads(Path(index).read_text())['packs']; lookup={}
    for pack, names in packs.items():
        for name in names:lookup.setdefault(name.casefold(),set()).add(pack)
    # Only Techniques enables effects. Sorting and saved sections can retain inactive ones.
    techniques=parser.get('UWT_PRESET','Techniques',fallback='')
    refs={PurePosixPath(v.replace('\\','/')).name for v in re.findall(r'@([^,\r\n]+\.fx)',techniques,re.I)}
    files=set(refs)
    bare=[v.strip() for v in techniques.split(',') if v.strip() and '@' not in v]
    unresolved=[]
    for name in bare:
        if (name+'.fx').casefold() in lookup:files.add(name+'.fx')
        else:unresolved.append(name+' (technique sans fichier .fx)')
    selected={'reshade-shaders'};unknown=[];ambiguous={}
    for name in sorted(files,key=str.casefold):
        options=lookup.get(name.casefold(),set())
        if len(options)==1:selected.update(options)
        elif not options:unknown.append(name)
        else:ambiguous[name]=sorted(options)
    # A pack already required by an unambiguous effect can cover a duplicate filename.
    for name, options in list(ambiguous.items()):
        if selected.intersection(options):del ambiguous[name]
    unknown+=unresolved
    return {'packs':sorted(selected),'files':sorted(files,key=str.casefold),'unknown':unknown,'ambiguous':ambiguous}


def report(value, fr=True):
    lines=[('Effets actifs référencés : ' if fr else 'Referenced active effects: ')+(', '.join(value['files']) or ('aucun' if fr else 'none')),
           ('Packs nécessaires : ' if fr else 'Required packs: ')+', '.join(value['packs']),
           ('Le téléchargement inclut les packs complets et leurs dépendances.' if fr else 'Downloads include complete packs and their dependencies.')]
    if value['unknown']:lines.append(('Effets non reconnus : ' if fr else 'Unknown effects: ')+', '.join(value['unknown'][:80]))
    for name, packs in list(value['ambiguous'].items())[:80]:
        lines.append(('Choix à vérifier : ' if fr else 'Check pack selection: ')+name+' : '+', '.join(packs))
    return '\n'.join(lines)
