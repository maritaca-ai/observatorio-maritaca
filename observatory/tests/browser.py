"""Exercise a locally served static build, including a project-path prefix."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--chrome', default='/usr/bin/google-chrome')
    args = parser.parse_args()
    origin = args.url.rstrip('/')
    with urlopen(origin+'/data.json') as response:
        data = json.load(response)
    reference = json.loads((ROOT/'verifier/reported.json').read_text())
    catalog = json.loads((ROOT/'observatory/catalog.json').read_text())
    errors, external, checked_cases = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome, headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: external.append(request.url)
                if urlsplit(request.url).netloc != urlsplit(origin).netloc else None)

        def go(route):
            page.goto(origin+'/#'+route, wait_until='networkidle')

        go('inicio?size=all&mode=all')
        assert page.locator('#home-title').inner_text().replace('\n',' ') == 'Observatório Maritaca'
        moving = page.locator('#sky-canvas').evaluate('(e)=>e.toDataURL()')
        page.wait_for_timeout(200)
        assert page.locator('#sky-canvas').evaluate('(e)=>e.toDataURL()') != moving
        page.locator('[data-sky-zoom=in]').click()
        assert page.locator('.model-sky').get_attribute('data-zoom') == '1.20'
        page.locator('.model-sky').focus()
        page.keyboard.press('ArrowLeft')
        assert page.locator('.model-sky').get_attribute('data-pan') != '0.000,0.000'
        page.locator('[data-sky-reset]').click()
        page.emulate_media(reduced_motion='reduce')
        page.wait_for_timeout(100)
        frozen = page.locator('#sky-canvas').evaluate('(e)=>e.toDataURL()')
        page.wait_for_timeout(200)
        assert page.locator('#sky-canvas').evaluate('(e)=>e.toDataURL()') == frozen
        page.emulate_media(reduced_motion='no-preference')

        # Independent JavaScript implementation must agree with the Git verifier.
        for selection, expected in reference['medias'].items():
            category, size, mode = selection.split('/')
            actual = page.evaluate('''({category,size,mode}) => {
              state.size=size;
              const variants=allVariants().filter(v=>inSizeGroup(v.model)&&(mode==='both'||v.mode===mode));
              const tasks=D.benchmarks.filter(b=>matchesCategory(b,category));
              return rankAverages(calculateAverages(tasks,variants,D.records)).map(r=>({
                model:r.variant.model.id,mode:r.variant.mode,rank:r.rank,
                cells:Object.fromEntries(Object.entries(r.cells).map(([k,c])=>[k,{
                  value:c.value,n:c.n,total:c.expected,benchmarks:c.entries.map(e=>e.task.id)}]))}));
            }''', dict(category=category,size=size,mode=mode))
            assert len(actual) == len(expected), selection
            for a, e in zip(actual, expected):
                assert [catalog['model_directories'][a['model']],a['mode'],a['rank']] == [e['modelo'],e['modo'],e['ranking']], (selection,a,e)
                for group, c in a['cells'].items():
                    r = e['medias'][group]
                    assert (c['value'] is None and r['valor'] is None) or abs(c['value']-r['valor']) < 1e-8, selection
                    assert [c['n'],c['total']] == [r['n'],r['total']], selection
                    assert sorted(catalog['benchmark_directories'][b] for b in c['benchmarks']) == sorted(r['benchmarks']), selection

        go('panorama?size=all&mode=all')
        assert page.locator('.score-table tbody tr').count() == len(data['benchmarks'])
        assert page.locator('.score-cell[data-result]').count() == len(data['records'])
        page.locator('[data-category=medico]').click()
        assert page.locator('.score-table tbody tr').count() == 2
        page.locator('[data-average-detail="candidate:thinking:total"]').click()
        assert page.locator('#detail-content .metric-breakdown tbody tr').count() == 2
        page.keyboard.press('Escape')
        page.locator('[data-category=all]').click()
        page.locator('[data-result="candidate:thinking:bluex_v2"]').click()
        assert page.locator('#detail-dialog').is_visible()
        assert 'Falhas do juiz' in page.locator('#detail-content').inner_text()
        page.keyboard.press('Escape')

        # Deep research is an overlapping category, not duplicated score rows.
        research_tasks = ['browsecomp_plus', 'draco', 'researchrubrics']
        go('panorama?size=all&mode=all&category=deep_research')
        assert page.locator('.results-heading h1').inner_text() == 'Deep research'
        assert page.locator('.score-table tbody tr').count() == 3
        page.locator('[data-average-detail="candidate:thinking:total"]').click()
        assert page.locator('#detail-content .metric-breakdown tbody tr').count() == 3
        page.keyboard.press('Escape')
        page.locator('.results-heading a[href*="tab=blind"]').click()
        page.locator('[data-arena-vote=tie]').wait_for()
        assert page.locator('#case-category').input_value() == 'deep_research'
        assert page.locator('#case-benchmark option').evaluate_all('(xs)=>xs.map(x=>x.value)') == research_tasks
        assert 'category=deep_research' in page.url
        page.reload(wait_until='networkidle')
        page.locator('[data-arena-vote=tie]').wait_for()
        assert page.locator('#case-category').input_value() == 'deep_research'
        assert page.locator('.answer-score').count() == 0
        go('comparar?size=all&mode=all&category=deep_research&task=draco')
        assert page.locator('#compare-benchmark option').evaluate_all('(xs)=>xs.map(x=>x.value)') == research_tasks
        go('metodo?section=benchmarks&mc=deep_research')
        assert page.locator('[data-method-benchmark]').count() == 3
        go('inicio?size=all&mode=all&category=deep_research')
        assert page.locator('[data-home-category]').input_value() == 'deep_research'

        # A real saved response from every displayed benchmark must open.
        for task in data['case_catalog']['benchmarks']:
            go(f'descobrir?task={task}&mode=thinking&size=all&a=candidate&b=qwen35-4b')
            page.wait_for_function('''task => experience.task===task && (
              experience.error || (experience.loadedTasks.has(task) && experience.cache.has(experience.key)))''', arg=task)
            assert not page.evaluate('experience.error'), task
            assert page.locator('.experience-answers .answer').count() == 2, task
            page.locator('.answer-evidence details').first.locator(':scope > summary').click()
            assert page.locator('.answer-evidence').first.inner_text(), task
            checked_cases.append(task)

        if 'longbench_v2' in data['case_catalog']['benchmarks']:
            go('descobrir?task=longbench_v2&mode=thinking&size=all')
            page.wait_for_function("experience.task==='longbench_v2' && experience.cache.has(experience.key)")
            checked_inputs = page.evaluate('''async () => {
              const refs=experience.cache.get(experience.key).responses.map(r=>r.input_messages_ref).filter(Boolean);
              const unique=[...new Map(refs.map(r=>[r.file,r])).values()];
              for (const ref of unique) {
                const text=await fetchExperienceText(ref.file);
                if (await digestText(text)!==ref.sha256) throw Error('Input reconstruction changed bytes');
                if (!Array.isArray(JSON.parse(text))) throw Error('Input messages not restored');
              }
              return unique.length;
            }''')
            assert checked_inputs > 1

        go('descobrir?task=capitu&mode=thinking&size=all&a=candidate&b=qwen35-4b')
        page.locator('.experience-answers').first.wait_for()
        page.select_option('#case-performance', 'different')
        page.wait_for_function("experience.cache.has(experience.key) && catalogPool().length>0")
        scores = page.locator('.answer-score').evaluate_all('(xs)=>xs.map(x=>Number(x.firstChild.textContent.trim().replace(",",".")))')
        assert sorted(scores) == [0,100], scores
        go('descobrir?task=conduta_bench&mode=instruct&size=all&a=gaia&b=manaca')
        page.wait_for_function("experience.task==='conduta_bench' && experience.cache.has(experience.key)")
        assert 'Gaia' in page.locator('.response-card h3').first.inner_text()
        assert 'Manacá' in page.locator('.response-card h3').last.inner_text()
        page.locator('[data-experience-tab=blind]').click()
        page.locator('[data-arena-vote=a]').wait_for()
        assert page.locator('.response-card h3').all_text_contents() == ['Resposta A','Resposta B']
        assert page.locator('.answer-score').count() == 0
        page.locator('[data-arena-vote=tie]').click()
        assert page.locator('.reveal-summary').is_visible()
        assert len(json.loads(page.evaluate("localStorage.getItem('observatorio-local-votes')"))) == 1
        page.locator('[data-experience=round]').last.click()
        page.locator('[data-arena-vote=a]').wait_for()
        assert page.locator('.answer-score').count() == 0

        # Research benchmarks participate in blind voting, with scores and
        # rubric judgments revealed only after the choice; votes never rescore.
        original_scores = page.evaluate('JSON.stringify(D.records.map(r=>[r.id,r.score]))')
        for task in ('draco', 'researchrubrics'):
            if task not in data['case_catalog']['benchmarks']:
                continue
            go(f'descobrir?task={task}&mode=all&size=all&a=candidate&b=qwen35-4b')
            page.wait_for_function('''task => experience.task===task &&
                experience.loadedTasks.has(task) && experience.cache.has(experience.key)''', arg=task)
            assert page.locator('.response-pair').count() == 2, task
            page.locator('[data-experience-tab=blind]').click()
            page.locator('[data-arena-vote=tie]').wait_for()
            assert page.locator('.response-card h3').all_text_contents() == ['Resposta A','Resposta B']
            assert page.locator('.answer-score').count() == 0
            assert page.locator('.answer-evidence').count() == 0
            page.locator('[data-arena-vote=tie]').click()
            assert page.locator('.reveal-summary').is_visible()
            assert page.locator('.answer-score').count() == 2
            page.locator('.answer-evidence details').first.locator(':scope > summary').click()
            assert page.locator('.answer-evidence').first.inner_text()
        assert page.evaluate('JSON.stringify(D.records.map(r=>[r.id,r.score]))') == original_scores

        go('comparar?models=candidate,gaia,qwen35-4b&mode=instruct&size=all&task=conduta_bench')
        assert page.locator('.plot-point').count() == 3
        page.select_option('#compare-benchmark','enade_qa')
        assert page.locator('.plot-point').count() == 3
        for route in ['inicio','panorama','comparar','modelos','metodo','descobrir?task=conduta_bench']:
            page.set_viewport_size({'width':390,'height':844})
            go(route)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), route

        # One denied fetch is shown once, then retried only on request.
        calls = []
        def denied_once(route):
            calls.append(route.request.url)
            if len(calls) == 1:
                route.fulfill(status=403, body='Synthetic denied request')
            else:
                route.continue_()
        page.route('**/cases/index.json', denied_once)
        go('descobrir?task=conduta_bench')
        page.reload(wait_until='networkidle')
        page.locator('[data-experience=retry]').wait_for()
        assert len(calls) == 1
        assert page.locator('a[href^="/signin-with-chatgpt"]').count() == 0
        page.locator('[data-experience=retry]').click()
        page.locator('.experience-answers').first.wait_for()
        assert len(calls) == 2
        # Model-provided markup remains literal text, never active HTML.
        assert page.evaluate('''() => {
          const el=document.createElement('div');
          el.innerHTML=readableAnswer('<img src=x onerror=alert(1)> **text** <script>alert(1)</script>');
          return !el.querySelector('img,script') && el.textContent.includes('<img');
        }''')
        assert not errors, errors
        assert not external, external
        browser.close()
    print(json.dumps(dict(average_filters=len(reference['medias']), benchmarks_with_answers=checked_cases,
                         browser_errors=errors, external_requests=external, passed=True)))


if __name__ == '__main__':
    main()
