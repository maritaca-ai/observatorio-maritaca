"""Check both interface languages against a locally served static build."""
import argparse
import json
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--chrome', default='/usr/bin/google-chrome')
    args = parser.parse_args()
    origin = args.url.rstrip('/')
    errors, external, checked = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome, headless=True, args=['--no-sandbox'])
        context = browser.new_context(locale='en-US', viewport={'width':1440, 'height':1000})
        context.add_init_script("localStorage.setItem('observatorio-language','en')")
        page = context.new_page()
        page.set_default_timeout(30000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: external.append(request.url)
                if urlsplit(request.url).netloc != urlsplit(origin).netloc else None)

        def go(route='inicio', lang=None):
            page.goto(origin + '/' + (f'?lang={lang}' if lang else '') + '#' + route, wait_until='networkidle')
            page.wait_for_function('()=>typeof D !== "undefined" && !!D')

        def switch(lang):
            page.locator(f'[data-language={lang}]').click()
            page.wait_for_function('(lang)=>i18n.language===lang', arg=lang)
            assert page.locator('html').get_attribute('lang') == ('pt-BR' if lang == 'pt' else 'en')
            assert page.locator(f'[data-language={lang}]').get_attribute('aria-pressed') == 'true'

        # Neither browser locale nor a saved preference overrides the PT default.
        go('panorama?size=all&mode=thinking&category=medico&models=candidate,qwen35-4b')
        assert page.locator('html').get_attribute('lang') == 'pt-BR'
        assert page.locator('#navigation').inner_text().startswith('Início')
        original = page.evaluate('JSON.stringify(D)')
        before = page.locator('[data-result]').evaluate_all('(xs)=>xs.map(x=>x.dataset.result)')
        hash_before = page.evaluate('location.hash')
        switch('en')
        assert page.locator('#navigation').inner_text().startswith('Home')
        assert page.evaluate('location.hash') == hash_before
        assert 'lang=en' in page.url
        assert page.locator('[data-result]').evaluate_all('(xs)=>xs.map(x=>x.dataset.result)') == before
        assert page.evaluate('JSON.stringify(D)') == original
        assert page.evaluate('number(1234.5)') == '1,234.50'
        page.reload(wait_until='networkidle')
        assert page.locator('html').get_attribute('lang') == 'en'
        switch('pt')
        assert page.evaluate('number(1234.5)') == '1.234,50'
        assert page.evaluate('JSON.stringify(D)') == original

        # Search keeps the same selection after a language change.
        go('panorama?size=all&mode=all', 'en')
        page.locator('#benchmark-search').fill('clinical')
        assert page.locator('.score-table tbody tr').count() == 1
        switch('pt')
        assert page.locator('#benchmark-search').input_value() == 'clinical'
        assert page.locator('.score-table tbody tr').count() == 1

        # Back/forward and the sky camera keep their language and filter state.
        go('panorama?size=all&mode=thinking&category=medico', 'en')
        page.locator('#navigation [data-view=modelos]').click()
        switch('pt')
        page.go_back(wait_until='networkidle')
        page.wait_for_function('()=>i18n.language==="en" && state.view==="panorama"')
        assert page.evaluate('state.category') == 'medico'
        go('inicio?size=all&mode=thinking', 'pt')
        page.locator('[data-sky-zoom=in]').click()
        camera = page.evaluate('JSON.stringify([home.zoom,home.panX,home.panY,[...state.selected]])')
        switch('en')
        assert page.evaluate('JSON.stringify([home.zoom,home.panX,home.panY,[...state.selected]])') == camera

        # Every benchmark description and metric is available in English.
        go('metodo?section=benchmarks', 'en')
        descriptions = page.evaluate('D.benchmarks.map(b=>b.description)')
        assert page.evaluate('(xs)=>xs.every(s=>i18n.english(s)!==s)', descriptions)
        assert page.locator('[data-method-benchmark]').count() == 24
        go('panorama?size=all&mode=all', 'en')
        page.locator('[data-result="candidate:thinking:bluex_v2"]').click()
        assert 'Judge failures' in page.locator('.result-audit').inner_text()
        assert 'Falhas do juiz' not in page.locator('.result-audit').inner_text()
        page.keyboard.press('Escape')

        # Prompts, responses and native judgments retain their original bytes.
        tasks = page.evaluate('Object.keys(D.case_catalog.benchmarks)')
        for task in tasks:
            go(f'descobrir?task={task}&mode=thinking&size=all&a=candidate&b=qwen35-4b', 'en')
            page.wait_for_function('''task=>experience.task===task && (
                experience.error || experience.cache.has(experience.key))''', arg=task)
            assert not page.evaluate('experience.error'), task
            page.wait_for_function('()=>document.querySelectorAll(".experience-answers .answer").length===2')
            assert page.locator('.experience-answers .answer').count() == 2, task
            saved = page.evaluate('JSON.stringify(experience.cache.get(experience.key))')
            evidence = page.locator('#app [translate=no]').all_text_contents()
            switch('pt')
            assert page.evaluate('JSON.stringify(experience.cache.get(experience.key))') == saved, task
            assert page.locator('#app [translate=no]').all_text_contents() == evidence, task
            switch('en')
            assert page.evaluate('JSON.stringify(experience.cache.get(experience.key))') == saved, task
            assert page.locator('#app [translate=no]').all_text_contents() == evidence, task
            checked.append(task)

        # Evidence containing interface words must still be left untouched.
        assert page.evaluate('''() => {
            const fixture=document.createElement('section');
            fixture.innerHTML='<span translate="no">Resultados</span><pre>Modelos</pre><button>Resultados</button>';
            document.body.append(fixture);i18n.apply(fixture);
            const ok=fixture.children[0].textContent==='Resultados'
                && fixture.children[1].textContent==='Modelos' && fixture.children[2].textContent==='Results';
            fixture.remove();return ok;
        }''')

        # Local preference interactions also work with English labels.
        page.locator('[data-experience-tab=blind]').click()
        page.locator('[data-arena-vote=a]').wait_for()
        round_before = page.evaluate('JSON.stringify(experience.round)')
        switch('pt')
        switch('en')
        assert page.evaluate('JSON.stringify(experience.round)') == round_before
        assert page.locator('.response-card h3').all_text_contents() == ['Response A','Response B']
        page.locator('[data-arena-vote=tie]').click()
        assert page.locator('.reveal-summary').is_visible()

        for lang in ['pt','en']:
            page.set_viewport_size({'width':390,'height':844})
            for route in ['inicio','panorama','comparar','modelos','metodo','descobrir?task=conduta_bench']:
                go(route,lang)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), (lang,route)
                assert page.locator('[data-language=en]').is_visible()
        assert not errors, errors
        assert not external, external
        browser.close()
    print(json.dumps({'passed':True, 'languages':['pt','en'], 'benchmarks_with_unchanged_evidence':checked,
                      'browser_errors':errors, 'external_requests':external}))


if __name__ == '__main__':
    main()
