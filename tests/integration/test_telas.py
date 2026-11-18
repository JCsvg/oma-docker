from textual.widgets import DataTable, Input, TabbedContent

from oma_docker.ui.abas import AbaCompose, AbaContainers, AbaImagens, AbaLimpeza, AbaRedes, AbaResumo, AbaVolumes
from oma_docker.ui.dialogos import Confirmar
from oma_docker.ui.navegacao import AjudaAba
from tests.conftest import esperar
from tests.integration.helpers import abrir, avisos, ir_para

TAM = (150, 44)


def cont(falso, nome):
    return next(c.id for c in falso.containers() if c.nome == nome)


async def test_abas_por_numero_seta_e_clique(app):
    async with app.run_test(size=TAM) as pilot:
        abas = app.query_one("#abas", TabbedContent)
        assert abas.active == "resumo"
        for n, nome in enumerate(["resumo", "containers", "imagens", "volumes", "redes", "compose", "limpeza", "terminal"], 1):
            await pilot.press(str(n))
            await pilot.pause(0.1)
            assert abas.active == nome
        await pilot.press("1")
        await pilot.pause(0.1)
        await pilot.press("alt+right")
        await pilot.pause(0.1)
        assert abas.active == "containers"
        await pilot.press("alt+h")
        await pilot.pause(0.1)
        assert abas.active == "resumo"
        await pilot.click("Tab#--content-tab-imagens")
        await pilot.pause(0.1)
        assert abas.active == "imagens"


async def test_resumo_cartoes_e_clique(app):
    async with app.run_test(size=TAM) as pilot:
        r = app.query_one(AbaResumo)
        assert await esperar(pilot, lambda: r.carregado)
        assert "Docker" in str(app.query_one("#estado-docker").render())
        await pilot.click("#card-imagens")
        await pilot.pause(0.2)
        assert app.aba_atual() == "imagens"


async def test_containers_listagem_grupos_e_estados(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        t = aba.query_one("#tabela", DataTable)
        chaves = [k.value for k in t.rows]
        assert "g:loja" in chaves and "g:blog" in chaves and "g:" in chaves
        assert len(chaves) == 6 + 3
        await pilot.press("g")  # sem agrupar
        await pilot.pause(0.1)
        assert t.row_count == 6
        await pilot.press("f")  # só rodando
        await pilot.pause(0.1)
        assert t.row_count == 2


async def test_iniciar_por_tecla_e_parar_por_clique(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await ir_para(pilot, aba, cont(falso, "mysql8"))
        await pilot.press("i")
        assert await esperar(pilot, lambda: ("iniciar", cont(falso, "mysql8")) in falso.chamadas)
        await esperar(pilot, lambda: next(c for c in falso.containers() if c.nome == "mysql8").estado == "running")
        await pilot.pause(0.3)
        await ir_para(pilot, aba, cont(falso, "mysql8"))
        await pilot.click("#b-parar")
        assert await esperar(pilot, lambda: ("parar", cont(falso, "mysql8")) in falso.chamadas)


async def test_remover_pede_confirmacao_e_cancelar_nao_apaga(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await ir_para(pilot, aba, cont(falso, "teste-rapido"))
        await pilot.press("x")
        await pilot.pause(0.1)
        assert isinstance(app.screen, Confirmar)
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not any(c[0] == "remover_container" for c in falso.chamadas)
        await pilot.press("x")
        await pilot.pause(0.1)
        await pilot.click("#ok")
        assert await esperar(pilot, lambda: any(c[0] == "remover_container" for c in falso.chamadas))


async def test_remover_por_teclado_puro(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await ir_para(pilot, aba, cont(falso, "teste-rapido"))
        await pilot.press("x")
        await pilot.pause(0.1)
        await pilot.press("ctrl+l")  # foco estava em Cancelar, vai para Remover
        await pilot.press("ctrl+enter")
        assert await esperar(pilot, lambda: any(c[0] == "remover_container" for c in falso.chamadas))


async def test_acao_em_titulo_de_grupo_avisa(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await ir_para(pilot, aba, "g:loja")
        await pilot.press("i")
        await pilot.pause(0.1)
        assert any("título de um grupo" in a for a in avisos(app))
        assert not falso.chamadas


async def test_erro_de_porta_em_linguagem_clara(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.click("#imagem")
        await pilot.press(*"alpine:3.22")
        await pilot.click("#portas")
        await pilot.press(*"3000:80")
        await pilot.click("#ok")
        assert await esperar(pilot, lambda: any("A porta 3000 já está em uso" in a for a in avisos(app)))
        assert not any("Traceback" in a for a in avisos(app))


async def test_rodar_container_por_formulario(app, falso):
    async with app.run_test(size=TAM) as pilot:
        await abrir(app, pilot, "2", AbaContainers)
        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.press(*"alpine:3.22")
        await pilot.press("ctrl+j")
        await pilot.press(*"novo-teste")
        await pilot.press("ctrl+j")
        await pilot.press(*"9191:80")
        await pilot.click("#ok")
        assert await esperar(pilot, lambda: any(c[0] == "rodar" for c in falso.chamadas))
        pedido = next(c[1] for c in falso.chamadas if c[0] == "rodar")
        assert (pedido.imagem, pedido.nome, pedido.portas) == ("alpine:3.22", "novo-teste", ["9191:80"])


async def test_formulario_valida_imagem_vazia(app):
    async with app.run_test(size=TAM) as pilot:
        await abrir(app, pilot, "2", AbaContainers)
        await pilot.press("n")
        await pilot.pause(0.2)
        await pilot.click("#ok")
        await pilot.pause(0.1)
        assert "Informe a imagem" in str(app.screen.query_one("#erro").render())


async def test_ajuda_por_ctrl_espaco_e_f1(app):
    async with app.run_test(size=TAM) as pilot:
        await abrir(app, pilot, "2", AbaContainers)
        await pilot.press("ctrl+space")
        await pilot.pause(0.1)
        assert isinstance(app.screen, AjudaAba)
        await pilot.press("escape")
        await pilot.pause(0.1)
        await pilot.press("f1")
        await pilot.pause(0.1)
        assert isinstance(app.screen, AjudaAba)
        await pilot.click("#fechar")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, AjudaAba)


async def test_filtro_por_barra(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await pilot.press("slash")
        assert isinstance(app.focused, Input)
        await pilot.press(*"mysql")
        await pilot.pause(0.1)
        t = aba.query_one("#tabela", DataTable)
        assert t.row_count == 1  # só mysql8 (sem projeto, sem título de grupo)
        await pilot.press(*"zzz")
        await pilot.pause(0.1)
        assert aba.query_one("#vazio").display and "Nada encontrado" in str(aba.query_one("#vazio").render())


async def test_rodape_enxuto_max_5(app):
    async with app.run_test(size=TAM) as pilot:
        await abrir(app, pilot, "2", AbaContainers)
        assert len(app.nav_da_aba().acoes_do_rodape()) <= 5


async def test_imagens_apagar_e_estado_de_uso(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "3", AbaImagens)
        t = aba.query_one("#tabela", DataTable)
        assert t.row_count == 7
        sem_tag = next(i.id for i in falso.imagens() if not i.tags)
        await ir_para(pilot, aba, sem_tag)
        await pilot.press("x")
        await pilot.pause(0.1)
        assert isinstance(app.screen, Confirmar)
        await pilot.click("#ok")
        assert await esperar(pilot, lambda: ("remover_imagem", sem_tag) in falso.chamadas)


async def test_volume_com_dados_mostra_reforco(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "4", AbaVolumes)
        await ir_para(pilot, aba, "mysql_dados")
        await pilot.press("x")
        await pilot.pause(0.1)
        textos = " ".join(str(w.render()) for w in app.screen.query("Static"))
        assert "ATENÇÃO" in textos and "Apagar não tem volta" in textos
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not any(c[0] == "remover_volume" for c in falso.chamadas)


async def test_criar_volume_e_rede(app, falso):
    async with app.run_test(size=TAM) as pilot:
        await abrir(app, pilot, "4", AbaVolumes)
        await pilot.press("c")
        await pilot.pause(0.1)
        await pilot.press(*"meu_vol")
        await pilot.press("enter")
        assert await esperar(pilot, lambda: ("criar_volume", "meu_vol") in falso.chamadas)
        await abrir(app, pilot, "5", AbaRedes)
        await pilot.click("#aba-redes #b-criar")
        await pilot.pause(0.1)
        await pilot.press(*"minha_rede")
        await pilot.click("#ok")
        assert await esperar(pilot, lambda: ("criar_rede", "minha_rede") in falso.chamadas)


async def test_rede_padrao_nao_apaga(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "5", AbaRedes)
        bridge = next(r.id for r in falso.redes() if r.nome == "bridge")
        await ir_para(pilot, aba, bridge)
        await pilot.press("x")
        await pilot.pause(0.1)
        assert any("padrão" in a for a in avisos(app))
        assert not isinstance(app.screen, Confirmar)


async def test_compose_subir_e_ver_containers(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "6", AbaCompose)
        await ir_para(pilot, aba, "blog")
        await pilot.press("u")
        assert await esperar(pilot, lambda: ("compose", "blog", "subir") in falso.chamadas)
        await pilot.pause(0.3)
        await ir_para(pilot, aba, "blog")
        await pilot.click("#b-containers")
        await pilot.pause(0.3)
        assert app.aba_atual() == "containers"
        assert app.query_one(AbaContainers).query_one("#filtro", Input).value == "blog"


async def test_limpeza_marcar_confirmar_e_apagar(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "7", AbaLimpeza)
        await pilot.press("x")  # nada marcado
        await pilot.pause(0.1)
        assert any("Nada marcado" in a for a in avisos(app))
        await pilot.click("#b-rede")
        await pilot.pause(0.1)
        assert aba.marcados
        t = aba.query_one("#tabela", DataTable)
        assert "[x]" in "".join(str(t.get_cell(r.value, t.ordered_columns[0].key)) for r in t.rows)
        await pilot.press("x")
        await pilot.pause(0.1)
        assert isinstance(app.screen, Confirmar)
        await pilot.click("#ok")
        assert await esperar(pilot, lambda: any(c[0] == "remover_rede" for c in falso.chamadas))
        assert not any(c[0] in ("remover_volume", "remover_container") for c in falso.chamadas)


async def test_limpeza_espaco_marca(app):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "7", AbaLimpeza)
        await pilot.press("space")
        await pilot.pause(0.1)
        assert len(aba.marcados) == 1
        await pilot.press("space")
        await pilot.pause(0.1)
        assert not aba.marcados


async def test_logs_ao_vivo_e_fechar(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await ir_para(pilot, aba, cont(falso, "loja-api"))
        await pilot.press("o")
        await pilot.pause(0.6)
        log = app.screen.query_one("#log")
        assert len(log.lines) >= 4
        assert app.estado.obter("log")["nome"] == "loja-api"
        await pilot.click("#fechar")
        await pilot.pause(0.2)
        assert app.estado.obter("log") is None


async def test_stats_e_detalhes(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await ir_para(pilot, aba, cont(falso, "loja-api"))
        await pilot.press("e")
        assert await esperar(pilot, lambda: "CPU" in str(app.screen.query_one("#corpo").render()))
        await pilot.press("escape")
        await pilot.pause(0.1)
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert "loja-api" in " ".join(str(w.render()) for w in app.screen.query("Static"))


async def test_baixar_imagem_com_progresso(app, falso):
    async with app.run_test(size=TAM) as pilot:
        await abrir(app, pilot, "3", AbaImagens)
        await pilot.press("b")
        await pilot.pause(0.1)
        await pilot.press(*"redis:8")
        await pilot.click("#ok")
        assert await esperar(pilot, lambda: ("baixar", "redis:8") in falso.chamadas)
        assert await esperar(pilot, lambda: "Pronto" in str(app.screen.query_one("#progresso").render()))


async def test_setas_sem_alt_nao_trocam_de_aba(app):
    async with app.run_test(size=TAM) as pilot:
        abas = app.query_one("#abas", TabbedContent)
        for n in ("1", "2", "3", "7"):
            await pilot.press(n)
            await pilot.pause(0.2)
            alvo = abas.active
            for k in ("left", "right", "h", "l", "up", "down"):
                await pilot.press(k)
                await pilot.pause(0.05)
            assert abas.active == alvo


async def test_alt_setas_valem_com_foco_em_campo_de_texto(app):
    async with app.run_test(size=TAM) as pilot:
        await abrir(app, pilot, "2", AbaContainers)
        await pilot.press("slash")
        assert isinstance(app.focused, Input)
        await pilot.press("alt+right")
        await pilot.pause(0.2)
        assert app.aba_atual() == "imagens"
        await pilot.press("alt+h")
        await pilot.pause(0.2)
        assert app.aba_atual() == "containers"


async def test_numeros_nao_trocam_aba_dentro_de_campo(app):
    async with app.run_test(size=TAM) as pilot:
        await abrir(app, pilot, "2", AbaContainers)
        await pilot.press("slash")
        await pilot.press("3")
        await pilot.pause(0.1)
        assert app.aba_atual() == "containers"
        assert app.query_one(AbaContainers).query_one("#filtro", Input).value == "3"


async def alcancados(app, pilot, aba):
    vistos = set()
    macros = (["down"] * 14, ["right"] * 12, ["up"] * 14, ["right"] * 3, ["left"] * 5, ["down", "right"], ["up", "left", "left", "up", "down", "down"], ["down"] * 3, ["l"] * 12, ["k"] * 14)
    for _ in range(1):
        for m in macros:
            for k in m:
                await pilot.press(k)
                f = app.focused
                if f is not None:
                    vistos.add(f)
    return vistos


async def test_setas_alcancam_todos_os_controles_de_cada_tela(app):
    from textual.widgets import Button
    async with app.run_test(size=TAM) as pilot:
        for n in "12345678":
            await pilot.press(n)
            await pilot.pause(0.4)
            aba = app.aba_widget()
            await pilot.press("escape")
            vistos = await alcancados(app, pilot, aba)
            esperados = [w for w in aba.query("Button, Input, Tabela, Card") if w.display and w.focusable and w.region.area > 0]
            faltam = [w for w in esperados if w not in vistos]
            assert not faltam, (aba.NOME, faltam)
            assert app.aba_atual() == aba.NOME


async def test_setas_no_formulario_e_na_confirmacao(app, falso):
    async with app.run_test(size=TAM) as pilot:
        aba = await abrir(app, pilot, "2", AbaContainers)
        await pilot.press("n")
        await pilot.pause(0.2)
        assert app.focused.id == "imagem"
        await pilot.press("down")
        assert app.focused.id == "nome"
        for _ in range(8):
            await pilot.press("down")
        assert app.focused.id == "cancelar"
        await pilot.press("right")
        assert app.focused.id == "ok"
        await pilot.press("escape")
        await pilot.pause(0.1)
        await ir_para(pilot, aba, cont(falso, "teste-rapido"))
        await pilot.press("x")
        await pilot.pause(0.1)
        assert app.focused.id == "cancelar"
        await pilot.press("l")
        assert app.focused.id == "ok"
