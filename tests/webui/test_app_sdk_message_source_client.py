"""Il kit delle app ascolta solo il guscio che lo ospita.

Il listener ``message`` di
``apps/jafta-sdk.js`` non guardava ``event.source``: un frame annidato
nell'app (una mappa, un video, una pagina esterna) poteva mandare
``jafta:ui-query`` e ricevere l'``outerHTML`` dell'app intera, o cambiarle tema
e navigazione. Il kit vero gira qui in node, come in
``test_app_sdk_swipe_client.py``.
"""

from __future__ import annotations

import json

from support.js_harness import ASSETS, requires_node, run_js

pytestmark = requires_node

SDK = (ASSETS / "apps" / "jafta-sdk.js").read_text(encoding="utf-8")


def _answers(source_expr: str) -> list:
    out = run_js(
        f"""
globalThis.location = {{
  search: '?token=t&overlay=1', pathname: '/apps/spesa/index.html',
  href: 'http://127.0.0.1:8080/apps/spesa/index.html?token=t&overlay=1',
}};
const root = {{ style: {{ setProperty() {{}} }}, setAttribute() {{}}, lang: '', outerHTML: '<html>app</html>' }};
globalThis.document = {{
  documentElement: root,
  addEventListener() {{}},
  querySelectorAll: () => [],
}};
globalThis.MutationObserver = class {{ observe() {{}} }};
globalThis.window = globalThis;
const listeners = [];
globalThis.addEventListener = (type, fn) => {{ if (type === 'message') listeners.push(fn); }};
globalThis.dispatchEvent = () => {{}};
globalThis.CustomEvent = class {{ constructor(t, o) {{ this.type = t; this.detail = o?.detail; }} }};
const posted = [];
const shell = {{ postMessage: (m) => posted.push(m) }};
globalThis.parent = shell;
const stranger = {{ postMessage() {{}} }};
{SDK}
await new Promise((r) => setTimeout(r, 0));
posted.length = 0;
for (const fn of listeners) fn({{ source: {source_expr}, data: {{ type: 'jafta:ui-query', nonce: 'n1' }} }});
console.log(JSON.stringify(posted.filter((m) => m.type === 'jafta:ui-result')));
"""
    )
    return json.loads(out.strip().splitlines()[-1])


def test_the_shell_gets_its_answer() -> None:
    answers = _answers("shell")
    assert len(answers) == 1 and answers[0]["nonce"] == "n1", answers


def test_a_nested_frame_gets_nothing() -> None:
    assert _answers("stranger") == []
