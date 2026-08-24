from pathlib import Path

from routes.cookbook_helpers import _parse_serve_phase


ROOT = Path(__file__).resolve().parent.parent
SERVE_SOURCE = (ROOT / "static/js/cookbookServe.js").read_text(encoding="utf-8")


def test_llama_cpp_and_ollama_require_a_scanned_gguf():
    assert "needsCachedGguf" in SERVE_SOURCE
    assert "_runnableGgufFiles(model).length === 0" in SERVE_SOURCE
    assert "llama.cpp and Ollama cannot load MLX or safetensors weights" in SERVE_SOURCE


def test_existing_ollama_models_are_not_rejected_by_the_gguf_guard():
    assert "&& !model?.is_ollama" in SERVE_SOURCE


def test_manually_entered_gguf_commands_remain_allowed():
    assert "!fields.manual_gguf_command" in SERVE_SOURCE
    assert "manual_gguf_command: _cmdManuallyEdited" in SERVE_SOURCE


def test_current_llama_cpp_listening_banner_marks_serve_ready():
    snapshot = "I srv  llama_server: server is listening on http://127.0.0.1:8000"
    assert _parse_serve_phase(snapshot) == {"phase": "ready", "status": "ready"}
