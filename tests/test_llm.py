"""Testes do roteamento em llm.py — modelo/thinking/tokens por caminho.

O cliente OpenAI é mockado: nenhum teste chama o servidor llama.cpp. Cada teste
captura os kwargs passados a `chat.completions.create` e verifica o roteamento.
"""

from types import SimpleNamespace

from work_assistant import config, llm


def _fake_client(capture):
    """Cliente falso que registra os kwargs e devolve um JSON vazio válido."""

    def create(**kwargs):
        capture.update(kwargs)
        message = SimpleNamespace(content="{}")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    completions = SimpleNamespace(create=create)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def _patch_client(monkeypatch, capture):
    monkeypatch.setattr(llm, "client", lambda *a, **k: _fake_client(capture))


def _thinking(cap):
    return cap["extra_body"]["chat_template_kwargs"]["enable_thinking"]


def test_complete_padrao_respeita_enable_thinking(monkeypatch):
    cap = {}
    _patch_client(monkeypatch, cap)
    monkeypatch.setattr(config, "ENABLE_THINKING", False)
    monkeypatch.setattr(config, "LLM_MODEL", "qwen3.5-4b")
    monkeypatch.setattr(config, "MAX_TOKENS", 2048)
    llm.complete("sys", "user")
    assert cap["model"] == "qwen3.5-4b"
    assert _thinking(cap) is False
    assert cap["max_tokens"] == 2048


def test_complete_qualidade_liga_thinking_e_teto_maior(monkeypatch):
    cap = {}
    _patch_client(monkeypatch, cap)
    monkeypatch.setattr(config, "QUALITY_MODEL", "qwen3.5-9b")
    monkeypatch.setattr(config, "QUALITY_ENABLE_THINKING", True)
    monkeypatch.setattr(config, "QUALITY_MAX_TOKENS", 4096)
    llm.complete("sys", "user", quality=True)
    assert cap["model"] == "qwen3.5-9b"
    assert _thinking(cap) is True
    assert cap["max_tokens"] == 4096


def test_complete_qualidade_sem_quality_model_cai_no_padrao(monkeypatch):
    cap = {}
    _patch_client(monkeypatch, cap)
    monkeypatch.setattr(config, "QUALITY_MODEL", "")  # modo qualidade desligado
    monkeypatch.setattr(config, "ENABLE_THINKING", False)
    monkeypatch.setattr(config, "LLM_MODEL", "qwen3.5-4b")
    llm.complete("sys", "user", quality=True)
    assert cap["model"] == "qwen3.5-4b"
    assert _thinking(cap) is False


def test_structured_nunca_usa_thinking_mesmo_na_qualidade(monkeypatch):
    cap = {}
    _patch_client(monkeypatch, cap)
    monkeypatch.setattr(config, "QUALITY_MODEL", "qwen3.5-9b")
    monkeypatch.setattr(config, "QUALITY_ENABLE_THINKING", True)
    llm.structured("sys", "user", {"type": "object"}, quality=True)
    assert cap["model"] == "qwen3.5-9b"
    assert _thinking(cap) is False
