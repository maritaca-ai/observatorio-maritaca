"""Atualiza somente as tabelas do README usando a referência verificada do Git."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '<!-- BEGIN VERIFIED RESULTS -->'
END = '<!-- END VERIFIED RESULTS -->'
BR = {'s5-nano', 'gaia-4b', 'manaca', 'tucano2-qwen-3.7b', 'lumi-4b'}


def render():
    read = lambda path: json.loads((ROOT/path).read_text())
    models, metrics, reference = read('results/modelos.json'), read('benchmarks/metrics.json'), read('verifier/reported.json')
    label = lambda model: models[model]['nome'] + (' 🇧🇷' if model in BR else '')
    def number(value, best):
        if value is None: return '—'
        text = f'{value:.2f}'.replace('.', ',')
        return f'**{text}**' if best is not None and abs(value-best) < 1e-8 else text
    lines = ['## Resultados', '', 'Médias e notas finais, separadas por modo. Os melhores valores de cada coluna de média ou linha de benchmark aparecem em **negrito**.', '']
    origins = ['native_br', 'translated_pt', 'international', 'total']
    for mode, title in [('thinking', 'Thinking'), ('instruct', 'Instruct')]:
        rows = reference['medias']['all/all/'+mode]
        best = {g:max(r['medias'][g]['valor'] for r in rows if r['medias'][g]['valor'] is not None) for g in origins}
        lines += [f'### {title}', '', '| Posição | Modelo | Nativo BR | Traduzido PT | Não nativo | Total | Testes |',
                  '|---:|---|---:|---:|---:|---:|---:|']
        for r in rows:
            cells = [str(r['ranking']), label(r['modelo'])] + [number(r['medias'][g]['valor'], best[g]) for g in origins]
            cells.append(f'{r["medias"]["total"]["n"]}/{r["medias"]["total"]["total"]}')
            lines.append('| '+' | '.join(cells)+' |')
        lines += ['', '<details>', f'<summary>Resultados por benchmark · {title}</summary>', '',
                  '| Benchmark | '+' | '.join(label(r['modelo']) for r in rows)+' |',
                  '|---|'+'---:|'*len(rows)]
        for benchmark, info in metrics.items():
            values = [reference['notas'].get(f'{r["modelo"]}/{benchmark}/{mode}') for r in rows]
            top = max((v for v in values if v is not None), default=None)
            lines.append('| '+info['name']+' | '+' | '.join(number(v, top) for v in values)+' |')
        lines += ['', '</details>', '']
    lines += ['[Explorar os registros finais](results/README.md) · [Conferir notas e médias](verifier/README.md)', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT/'README.md'
    old = path.read_text()
    before, rest = old.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    updated = before+BEGIN+'\n\n'+render()+'\n'+END+after
    if args.check:
        if old != updated: raise SystemExit('As tabelas do README diferem da referência verificada.')
        print('Tabelas do README conferidas.')
    else:
        path.write_text(updated)


if __name__ == '__main__':
    main()
