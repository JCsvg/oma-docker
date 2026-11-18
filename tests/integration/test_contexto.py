import json
import shutil
import subprocess

import pytest
from textual.widgets import DataTable, Input

from oma_docker.app import OmaDockerApp
from oma_docker.services.estado import Estado
from oma_docker.services.falso import ClienteFalso
from oma_docker.services.terminal import Tmux
from oma_docker.ui.abas import AbaContainers, AbaImagens, AbaTerminal
from oma_docker.ui.abertura import Abertura
from oma_docker.ui.dialogos import Confirmar, TelaLogs
from oma_docker.ui.formulario import FormularioRodar
from tests.conftest import esperar
from tests.integration.helpers import abrir, ir_para

TAM = (150, 44)


def novo(estado, anexos, abertura=False):
    return OmaDockerApp(cliente=ClienteFalso(), estado=estado, tmux=Tmux(estado.pasta / "tmux.sock"), abertura=abertura, anexador=anexos.append)


async def test_abertura_so_na_primeira_vez_do_boot(estado, anexos):
    a1 = novo(estado, anexos, abertura=True)
    async with a1.run_test(size=TAM) as pilot:
        await pilot.pause(0.3)
        assert isinstance(a1.screen, Abertura)
        assert "█" in str(a1.screen.query_one("#logo").render())
        await pilot.press("x")  # qualquer tecla
        await pilot.pause(0.2)
        assert not isinstance(a1.screen, Abertura)
    assert estado.ja_abriu()
    a2 = novo(Estado(estado.pasta), anexos, abertura=True)  # segunda abertura no mesmo boot
    async with a2.run_test(size=TAM) as pilot:
        await pilot.pause(0.5)
        assert not isinstance(a2.screen, Abertura)


async def test_abertura_passa_com_clique_e_com_tempo(estado, anexos):
    a = novo(estado, anexos, abertura=True)
    async with a.run_test(size=TAM) as pilot:
        await pilot.pause(0.3)
        assert isinstance(a.screen, Abertura)
        await pilot.click("#logo")
        await pilot.pause(0.2)
        assert not isinstance(a.screen, Abertura)
    estado.marcador.unlink()
    b = novo(estado, anexos, abertura=True)
    async with b.run_test(size=TAM) as pilot:
        await pilot.pause(0.3)
        assert isinstance(b.screen, Abertura)
        assert await esperar(pilot, lambda: not isinstance(b.screen, Abertura), 3)


@pytest.mark.parametrize("tam,grande", [((80, 24), True), ((200, 50), True), ((50, 20), False)])
async def test_banner_em_varios_tamanhos(estado, anexos, tam, grande):
    a = novo(estado, anexos, abertura=True)
    async with a.run_test(size=tam) as pilot:
        await pilot.pause(0.3)
        texto = str(a.screen.query_one("#logo").render())
        assert ("█" in texto) == grande
        if not grande:
            assert texto.strip() == "OMA DOCKER"
        assert a.screen.query_one("#logo").region.width <= tam[0]


async def test_contexto_restaurado_ao_reabrir(estado, anexos):
    a = novo(estado, anexos)
    async with a.run_test(size=TAM) as pilot:
        aba = await abrir(a, pilot, "3", AbaImagens)
        alvo = [i.id for i in a.cliente.imagens() if i.nome == "nginx:1.27"][0]
        await ir_para(pilot, aba, alvo)
        await pilot.press("u")  # só sem uso
        await pilot.pause(0.2)
        await pilot.press("slash")
        await pilot.press(*"a")
        await pilot.pause(0.2)
    dados = json.loads(estado.arquivo.read_text())["dados"]
    assert dados["aba"] == "imagens" and dados["aba_imagens"]["filtro"] == "a" and dados["aba_imagens"]["so_sem_uso"] is True
    b = novo(Estado(estado.pasta), anexos)
    async with b.run_test(size=TAM) as pilot:
        await pilot.pause(0.5)
        assert b.aba_atual() == "imagens"
        aba = b.query_one(AbaImagens)
        assert aba.query_one("#filtro", Input).value == "a"
        assert aba.so_sem_uso is True


async def test_cursor_restaurado(estado, anexos):
    a = novo(estado, anexos)
    async with a.run_test(size=TAM) as pilot:
        aba = await abrir(a, pilot, "2", AbaContainers)
        alvo = next(c.id for c in a.cliente.containers() if c.nome == "mysql8")
        await ir_para(pilot, aba, alvo)
        await pilot.pause(0.2)
    b = novo(Estado(estado.pasta), anexos)
    async with b.run_test(size=TAM) as pilot:
        aba = b.query_one(AbaContainers)
        assert await esperar(pilot, lambda: aba.carregado)
        await pilot.pause(0.3)
        assert aba.chave_atual() == alvo


async def test_log_seguido_volta_ao_reabrir(estado, anexos):
    a = novo(estado, anexos)
    async with a.run_test(size=TAM) as pilot:
        aba = await abrir(a, pilot, "2", AbaContainers)
        await ir_para(pilot, aba, next(c.id for c in a.cliente.containers() if c.nome == "loja-api"))
        await pilot.press("o")
        await pilot.pause(0.3)
        assert isinstance(a.screen, TelaLogs)
    b = novo(Estado(estado.pasta), anexos)
    async with b.run_test(size=TAM) as pilot:
        assert await esperar(pilot, lambda: isinstance(b.screen, TelaLogs))
        assert b.screen.nome == "loja-api"


async def test_rascunho_volta_e_segredo_nao_e_gravado(estado, anexos):
    a = novo(estado, anexos)
    async with a.run_test(size=TAM) as pilot:
        await abrir(a, pilot, "2", AbaContainers)
        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.press(*"alpine:3.22")
        await pilot.click("#ambiente")
        await pilot.press(*"MODO=a DB_PASSWORD=segredo123 API_TOKEN=xyz")
        await pilot.pause(0.2)
        assert isinstance(a.screen, FormularioRodar)
    bruto = estado.arquivo.read_text()
    assert "segredo123" not in bruto and "xyz" not in bruto and "DB_PASSWORD" not in bruto
    assert "MODO=a" in bruto
    b = novo(Estado(estado.pasta), anexos)
    async with b.run_test(size=TAM) as pilot:
        assert await esperar(pilot, lambda: isinstance(b.screen, FormularioRodar) and len(b.screen.query("#imagem")) == 1)
        assert b.screen.query_one("#imagem", Input).value == "alpine:3.22"
        assert b.screen.query_one("#ambiente", Input).value == "MODO=a"


async def test_contexto_corrompido_nao_quebra(estado, anexos):
    estado.preparar()
    estado.arquivo.write_text("lixo{{{")
    a = novo(estado, anexos)
    async with a.run_test(size=TAM) as pilot:
        await pilot.pause(0.3)
        assert a.aba_atual() == "resumo"


needs_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="sem tmux")


@needs_tmux
async def test_terminal_abrir_nova_janela_e_encerrar(estado, anexos):
    a = novo(estado, anexos)
    try:
        async with a.run_test(size=TAM) as pilot:
            await abrir(a, pilot, "8", AbaTerminal)
            await pilot.press("t")
            await pilot.pause(0.5)
            assert anexos and anexos[-1][-3:-1] == ["attach-session", "-t"]
            assert a.tmux.ativo()
            await pilot.click("#aba-terminal #b-nova")
            await pilot.pause(0.5)
            assert len(a.tmux.janelas()) == 2
            await pilot.press("x")
            await pilot.pause(0.2)
            assert isinstance(a.screen, Confirmar)
            await pilot.click("#ok")
            await pilot.pause(0.5)
            assert not a.tmux.ativo()
    finally:
        a.tmux.encerrar()


@needs_tmux
@pytest.mark.skipif(shutil.which("nvim") is None, reason="sem nvim")
async def test_editar_arquivo_abre_nvim_e_sobrevive_ao_fechar(estado, anexos, tmp_path):
    arq = tmp_path / "docker-compose.yml"
    arq.write_text("services: {}\n")
    a = novo(estado, anexos)
    try:
        async with a.run_test(size=TAM) as pilot:
            await abrir(a, pilot, "8", AbaTerminal)
            await pilot.press("e")
            await pilot.pause(0.2)
            await pilot.press(*str(arq))
            await pilot.press("enter")
            await pilot.pause(0.8)
            assert a.tmux.tem_editor()
        # app fechado: reabre no mesmo "boot" e a janela do nvim continua lá
        b = novo(Estado(estado.pasta), anexos)
        async with b.run_test(size=TAM) as pilot:
            aba = await abrir(b, pilot, "8", AbaTerminal)
            assert await esperar(pilot, lambda: any(j.nome == "editar-docker-compose.yml" for j in aba.dados))
            assert b.tmux.tem_editor()
    finally:
        a.tmux.encerrar()
        subprocess.run(["pkill", "-f", f"nvim --embed {tmp_path}"])


async def test_editar_arquivo_inexistente_avisa(app):
    async with app.run_test(size=TAM) as pilot:
        app.editar_arquivo("/nao/existe/compose.yml", "/nao/existe", "x")
        await pilot.pause(0.1)
        assert any("não encontrado" in n.message for n in app._notifications)


async def test_sem_tmux_cai_para_shell_sem_persistencia(estado, anexos, monkeypatch):
    monkeypatch.setattr(Tmux, "disponivel", lambda self: False)
    a = novo(estado, anexos)
    async with a.run_test(size=TAM) as pilot:
        a.abrir_terminal()
        await pilot.pause(0.1)
        assert any("não está instalado" in n.message for n in a._notifications)
        assert anexos  # abriu o shell mesmo assim
