"""Verificações estáticas do frontend (arquivo único, sem build).

Nenhum teste executa a interface — não há runner de JS no projeto e adicionar um
violaria o "sem build". O que dá para garantir sem browser: que o arquivo não
busca nada na rede, que toda variável de cor existe nos dois temas, e que o
script ao menos compila. O `node --check` é oportunista: pula se não houver node.
"""

import re
import shutil
import subprocess

import pytest

from work_assistant.web import api

INDEX = api.STATIC_DIR / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text()


def test_no_external_requests(html):
    """O app roda 100% local: nada de CDN, fonte remota ou script externo."""
    urls = set(re.findall(r"https?://[^\"' )]+", html))
    # A namespace do SVG é identificador XML, não requisição.
    urls.discard("http://www.w3.org/2000/svg")
    assert not urls, f"referências externas no frontend: {sorted(urls)}"


def test_no_hardcoded_font_families(html):
    """Famílias vêm de --font-sans/--font-mono, senão o fallback offline vira loteria."""
    assert "JetBrains Mono" not in html
    assert "Bricolage" not in html
    assert "--font-sans:" in html and "--font-mono:" in html


def test_every_colour_variable_has_a_dark_counterpart(html):
    """Variável sem contraparte em body.dark renderiza invisível no tema escuro."""
    light = re.search(r"^body \{(.*?)^\}", html, re.S | re.M)
    dark = re.search(r"^body\.dark \{(.*?)^\}", html, re.S | re.M)
    assert light and dark, "blocos de tema não encontrados"

    def declared(block: str) -> set[str]:
        return set(re.findall(r"(--[a-z0-9-]+)\s*:", block))

    # Fontes não mudam com o tema; só cores precisam de par.
    faltando = declared(light.group(1)) - declared(dark.group(1)) - {"--font-sans", "--font-mono"}
    assert not faltando, f"sem contraparte em body.dark: {sorted(faltando)}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node não disponível")
def test_script_compiles(tmp_path, html):
    """Rede de segurança mínima para o frontend, que nenhum outro teste cobre."""
    script = re.search(r"<script>\n(.*)</script>", html, re.S)
    assert script, "bloco <script> não encontrado"
    js = tmp_path / "app.js"
    js.write_text(script.group(1))
    result = subprocess.run(
        ["node", "--check", str(js)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
