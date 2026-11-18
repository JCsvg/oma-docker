import shutil
import subprocess
import time

import pytest

from oma_docker.services.terminal import SESSAO, Tmux, comando_editar, comando_shell_container

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="sem tmux")


@pytest.fixture
def tmux(tmp_path):
    t = Tmux(tmp_path / "t.sock")
    yield t
    t.encerrar()
    subprocess.run(["pkill", "-f", f"nvim --embed {tmp_path}"])  # o nvim deixa um processo --embed para trás


def test_sessao_sobrevive_ao_app(tmux, tmp_path):
    assert not tmux.ativo()
    tmux.garantir(str(tmp_path))
    tmux.nova_janela("dorme", "sleep 600")
    # "fechar o app": outro objeto Tmux no mesmo socket reencontra tudo
    outro = Tmux(tmux.socket)
    assert outro.ativo()
    nomes = [j.nome for j in outro.janelas()]
    assert nomes == ["shell", "dorme"]
    pids = subprocess.run(["pgrep", "-f", f"sleep 600"], capture_output=True, text=True).stdout.split()
    assert pids


def test_enviar_comando_e_encerrar(tmux, tmp_path):
    tmux.garantir(str(tmp_path))
    marca = tmp_path / "feito"
    tmux.enviar(1, f"touch {marca}")
    for _ in range(40):
        if marca.exists():
            break
        time.sleep(0.05)
    assert marca.exists()
    tmux.encerrar()
    assert not tmux.ativo() and not tmux.socket.exists()


def test_nvim_dentro_do_tmux(tmux, tmp_path):
    if shutil.which("nvim") is None:
        pytest.skip("sem nvim")
    arq = tmp_path / "docker-compose.yml"
    arq.write_text("services: {}\n")
    tmux.nova_janela("editar", comando_editar(str(arq)), str(tmp_path))
    for _ in range(60):
        if tmux.tem_editor():
            break
        time.sleep(0.05)
    assert tmux.tem_editor()
    # mesmo "fechando o app", o nvim segue vivo e com o arquivo aberto
    assert Tmux(tmux.socket).tem_editor()
    saida = ""
    for _ in range(80):
        saida = subprocess.run([*tmux._base(), "capture-pane", "-p", "-t", f"{SESSAO}:editar"], capture_output=True, text=True).stdout
        if "services" in saida:
            break
        time.sleep(0.05)
    assert "docker-compose.yml" in saida or "services" in saida


def test_comandos_com_aspas():
    assert comando_editar("/a b/c.yml") == "nvim '/a b/c.yml'"
    assert "docker exec -it abc" in comando_shell_container("abc")


def test_sem_tmux_no_path(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    t = Tmux(tmp_path / "x.sock")
    assert not t.disponivel() and not t.ativo() and t.janelas() == []
