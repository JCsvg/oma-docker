"""As telas (abas) do app. Cada ação tem tecla e botão equivalentes."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Static

from oma_docker.services.erros import traduzir
from oma_docker.services.modelos import Container, Estatistica, Imagem, ItemLimpeza, ProjetoCompose, Rede, Volume, humano
from oma_docker.services.util import itens_de_limpeza, projetos_de
from oma_docker.ui.dialogos import Baixar, Confirmar, Detalhes, Entrada, TelaLogs, TelaStats
from oma_docker.ui.formulario import FormularioRodar
from oma_docker.ui.navegacao import NavegacaoMixin


def data(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y") if ts else "?"


def B(tecla: str, acao: str, desc: str, **kw) -> Binding:
    return Binding(tecla, f"acao('{acao}')", desc, **kw)


class AbaLista(NavegacaoMixin, Vertical):
    """Base: filtro, tabela, estado vazio e fileira de botões. Os filhos dão colunas, dados e ações."""

    NOME = ""
    COLUNAS: tuple[str, ...] = ()
    ACOES: tuple[tuple[str, str], ...] = ()  # (id da ação, rótulo do botão com a tecla)
    VAZIO = "Nada por aqui."
    CADA = 1  # atualiza a cada N ciclos de 2 s

    BINDINGS = [
        Binding("j", "cursor(1)", "Descer", show=False),
        Binding("k", "cursor(-1)", "Subir", show=False),
        Binding("right", "app.aba_relativa(1)", "Próxima tela", show=False),
        Binding("left", "app.aba_relativa(-1)", "Tela anterior", show=False),
        Binding("slash", "buscar", "Filtrar", key_display="/"),
        Binding("enter", "acao('detalhes')", "Detalhes", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(id=f"aba-{self.NOME}")
        self.dados: list = []
        self.itens: dict[str, object] = {}
        self.carregado = False
        self.carregado_uma_vez = False
        self._buscando = False
        self._ciclo = 0
        self._cursor_pendente: str | None = None
        self.erro = ""

    # estrutura
    def compose(self) -> ComposeResult:
        with Horizontal(id="barra"):
            yield Input(placeholder="Filtrar (tecla /)", id="filtro")
            yield from self.barra()
        yield DataTable(id="tabela", cursor_type="row", zebra_stripes=False)
        yield Static("", id="vazio")
        with Horizontal(id="acoes"):
            for id_, rot in self.ACOES:
                yield Button(rot, id=f"b-{id_}", name=id_)

    def barra(self) -> ComposeResult:
        return ()

    def on_mount(self) -> None:
        t = self.query_one("#tabela", DataTable)
        for c in self.COLUNAS:
            t.add_column(c)
        self.set_interval(2, self._poll)
        self.recarregar()

    # dados
    def buscar(self):
        raise NotImplementedError

    def linhas(self, dados) -> list[tuple[str, list]]:
        raise NotImplementedError

    def filtrar(self, dados: list, texto: str) -> list:
        return dados

    def _poll(self) -> None:
        self._ciclo += 1
        if self.app.aba_atual() == self.NOME and len(self.app.screen_stack) == 1 and self._ciclo % self.CADA == 0:
            self.recarregar()

    def recarregar(self) -> None:
        if self._buscando:
            return
        self._buscando = True
        threading.Thread(target=self._thread, daemon=True).start()

    def _thread(self) -> None:
        try:
            dados, erro = self.buscar(), ""
        except Exception as e:
            dados, erro = None, traduzir(e)
        try:
            self.app.call_from_thread(self._aplicar, dados, erro)
        except Exception:
            self._buscando = False

    def _aplicar(self, dados, erro: str) -> None:
        self._buscando = False
        self.erro = erro
        if dados is not None:
            self.dados = dados
            self.carregado = True
        self.renderizar()

    def texto_filtro(self) -> str:
        return self.query_one("#filtro", Input).value.strip().lower()

    def renderizar(self) -> None:
        t = self.query_one("#tabela", DataTable)
        vazio = self.query_one("#vazio", Static)
        if self.erro and not self.carregado:
            t.display = False
            vazio.display = True
            vazio.update(Text(self.erro, style="bold red"))
            return
        dados = self.filtrar(self.dados, self.texto_filtro())
        linhas = self.linhas(dados)
        antes = self._cursor_pendente or self.chave_atual()
        t.clear()
        self.itens = {}
        for chave, celulas in linhas:
            t.add_row(*celulas, key=chave)
        if linhas:
            chaves = [c for c, _ in linhas]
            if antes in chaves:
                alvo = chaves.index(antes)
            elif not self.carregado_uma_vez:
                alvo = next((n for n, c in enumerate(chaves) if not c.startswith("g:")), 0)
            else:
                alvo = min(t.cursor_row, len(chaves) - 1)
            self.carregado_uma_vez = True
            t.move_cursor(row=max(alvo, 0), animate=False)
            if self._cursor_pendente and antes in chaves:
                self._cursor_pendente = None
        t.display = bool(linhas)
        vazio.display = not linhas
        if not linhas:
            vazio.update(Text(self.VAZIO if not self.texto_filtro() else f"Nada encontrado para \"{self.texto_filtro()}\". Apague o filtro para ver tudo."))
        self.depois_de_renderizar()

    def depois_de_renderizar(self) -> None:
        pass

    def chave_atual(self) -> str | None:
        t = self.query_one("#tabela", DataTable)
        if not t.display or t.row_count == 0:
            return None
        try:
            return t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        except Exception:
            return None

    def selecionado(self):
        k = self.chave_atual()
        return self.mapa().get(k) if k else None

    def mapa(self) -> dict:
        return {}

    # estado salvo
    def estado(self) -> dict:
        return {"filtro": self.query_one("#filtro", Input).value, "cursor": self.chave_atual()}

    def restaurar(self, d: dict) -> None:
        if not isinstance(d, dict):
            return
        if isinstance(d.get("filtro"), str):
            self.query_one("#filtro", Input).value = d["filtro"]
        if isinstance(d.get("cursor"), str):
            self._cursor_pendente = d["cursor"]
        if self.carregado:
            self.renderizar()

    def guardar(self) -> None:
        if self.is_mounted:
            self.app.guardar_aba(self.NOME, self.estado())

    @on(DataTable.RowHighlighted)
    def _linha_mudou(self, ev: DataTable.RowHighlighted) -> None:
        if self._cursor_pendente is None:  # com restauração em curso, o cursor ainda não é o do usuário
            self.guardar()

    @on(Input.Changed, "#filtro")
    def _filtro_mudou(self, ev: Input.Changed) -> None:
        self.renderizar()
        self.guardar()

    @on(Input.Submitted, "#filtro")
    def _filtro_enter(self, ev: Input.Submitted) -> None:
        self.query_one("#tabela", DataTable).focus()

    @on(DataTable.RowSelected)
    def _linha_aberta(self, ev: DataTable.RowSelected) -> None:
        ev.stop()
        self.action_acao("detalhes")

    @on(Button.Pressed)
    def _botao(self, ev: Button.Pressed) -> None:
        if ev.button.name:
            ev.stop()
            self.action_acao(ev.button.name)

    # ações
    def action_buscar(self) -> None:
        self.query_one("#filtro", Input).focus()

    def action_cursor(self, passo: int) -> None:
        t = self.query_one("#tabela", DataTable)
        if not t.has_focus:
            return
        t.action_cursor_down() if passo > 0 else t.action_cursor_up()

    def action_acao(self, nome: str) -> None:
        f = getattr(self, f"acao_{nome}", None)
        if f:
            f()

    def pedir_selecao(self, o=None):
        s = self.selecionado()
        if s is None:
            self.app.notify("Selecione uma linha da lista primeiro.", severity="warning")
        return s

    def detalhes_texto(self, titulo: str, linhas: list[tuple[str, str]]) -> None:
        self.app.push_screen(Detalhes(titulo, linhas))

    def acao_detalhes(self) -> None:
        pass


# ---------------------------------------------------------------- Resumo

class Card(Static, can_focus=True):
    DEFAULT_CSS = """
    Card { border: round $panel; padding: 0 1; height: 100%; }
    Card:focus { border: round $accent; }
    Card:hover { border: round $accent; }
    """
    BINDINGS = [Binding("enter", "abrir", "Abrir", show=False)]

    def __init__(self, destino: str, **kw) -> None:
        super().__init__(**kw)
        self.destino = destino

    def action_abrir(self) -> None:
        self.app.action_aba(self.destino)

    def on_click(self, ev: events.Click) -> None:
        self.action_abrir()


class AbaResumo(NavegacaoMixin, Vertical):
    NOME = "resumo"
    CADA = 3
    RODAPE = ("acao('rodar')", "acao('baixar')", "acao('limpeza')")
    BINDINGS = [
        B("n", "rodar", "Rodar container"),
        B("b", "baixar", "Baixar imagem"),
        B("c", "limpeza", "Ir para a limpeza"),
        Binding("right", "app.aba_relativa(1)", "Próxima tela", show=False),
        Binding("left", "app.aba_relativa(-1)", "Tela anterior", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(id="aba-resumo")
        self._buscando = False
        self._ciclo = 0
        self.carregado = False
        self.dados: dict = {}

    def compose(self) -> ComposeResult:
        yield Static(Text("OMA DOCKER", style="bold"), id="marca")
        yield Static("", id="estado-docker")
        with Grid(id="cartoes"):
            for nome, dest in (("containers", "containers"), ("imagens", "imagens"), ("volumes", "volumes"),
                               ("redes", "redes"), ("disco", "limpeza"), ("limpeza", "limpeza")):
                yield Card(dest, id=f"card-{nome}")
        with Horizontal(id="acoes"):
            yield Button("Rodar container (n)", id="b-rodar", name="rodar")
            yield Button("Baixar imagem (b)", id="b-baixar", name="baixar")
            yield Button("Limpeza (c)", id="b-limpeza", name="limpeza")

    def on_mount(self) -> None:
        self.set_interval(2, self._poll)
        self.recarregar()

    def _poll(self) -> None:
        self._ciclo += 1
        if self.app.aba_atual() == self.NOME and len(self.app.screen_stack) == 1 and self._ciclo % self.CADA == 0:
            self.recarregar()

    def recarregar(self) -> None:
        if self._buscando:
            return
        self._buscando = True
        threading.Thread(target=self._thread, daemon=True).start()

    def _thread(self) -> None:
        c = self.app.cliente
        try:
            d = {"conts": c.containers(), "imgs": c.imagens(), "vols": c.volumes(), "redes": c.redes(), "uso": c.uso_disco(),
                 "versao": c.versao()}
            erro = ""
        except Exception as e:
            d, erro = None, traduzir(e)
        try:
            self.app.call_from_thread(self._aplicar, d, erro)
        except Exception:
            self._buscando = False

    def _aplicar(self, d, erro: str) -> None:
        self._buscando = False
        est = self.query_one("#estado-docker", Static)
        if d is None:
            est.update(Text("● " + erro, style="bold red"))
            return
        self.dados, self.carregado = d, True
        est.update(Text.assemble(("● ", "green"), f"Docker {d['versao']} conectado" + ("" if self.app.demo else "")))
        conts, imgs, vols, redes, uso = d["conts"], d["imgs"], d["vols"], d["redes"], d["uso"]
        rod = sum(c.estado == "running" for c in conts)
        par = len(conts) - rod
        livres = [v for v in vols if not v.em_uso]
        anon = [v for v in livres if v.anonimo]
        itens = itens_de_limpeza(conts, imgs, vols, redes)

        def cartao(id_, titulo, grande, linhas):
            t = Text()
            t.append(titulo + "\n", style="bold")
            t.append(str(grande) + "\n", style="bold")
            for l in linhas:
                t.append(l + "\n", style="dim")
            self.query_one(f"#card-{id_}", Card).update(t)

        cartao("containers", "Containers", len(conts), [f"{rod} rodando", f"{par} parados"])
        cartao("imagens", "Imagens", len(imgs), [f"{sum(i.em_uso for i in imgs)} em uso", f"{humano(sum(i.tamanho for i in imgs))} no total"])
        cartao("volumes", "Volumes", len(vols), [f"{len(livres)} sem uso", f"{len(anon)} sem nome e sem uso"])
        cartao("redes", "Redes", len(redes), [f"{sum(1 for r in redes if not r.padrao)} criadas por você"])
        cartao("disco", "Disco usado", humano(uso.total), [f"imagens {humano(uso.imagens_total)}", f"volumes {humano(uso.volumes_total)}"])
        cartao("limpeza", "Recuperável", humano(uso.recuperavel), [f"{len(itens)} itens para limpar", "abrir a Limpeza"])

    def estado(self) -> dict:
        return {}

    def restaurar(self, d: dict) -> None:
        pass

    def focar_entrada(self) -> None:
        self.query_one("#card-containers").focus()

    def zonas(self):
        cards = [w for w in self.query(Card)]
        botoes = [w for w in self.query("#acoes Button")]
        return [cards, botoes]

    def fileira(self):
        z = self.zona_atual()
        zs = self.zonas()
        return list(zs[z]) if z >= 0 else []

    def acoes_do_rodape(self):
        return list(self.RODAPE) + ["ajuda_aba"]

    @on(Button.Pressed)
    def _botao(self, ev: Button.Pressed) -> None:
        ev.stop()
        self.action_acao(ev.button.name or "")

    def action_acao(self, nome: str) -> None:
        if nome == "rodar":
            self.app.rodar_novo()
        elif nome == "baixar":
            self.app.baixar_imagem()
        elif nome == "limpeza":
            self.app.action_aba("limpeza")

    def action_cursor(self, passo: int) -> None:
        self.mover_secao(passo)


# ------------------------------------------------------------ Containers

ESTADOS = {"running": ("●", "rodando", "success"), "paused": ("‖", "pausado", "warning"), "exited": ("○", "parado", "muted"),
           "created": ("○", "criado", "muted"), "restarting": ("↻", "reiniciando", "warning"), "dead": ("✖", "morto", "error")}


def celula_estado(app, c: Container) -> Text:
    ic, nome, cor = ESTADOS.get(c.estado, ("?", c.estado, "muted"))
    if c.estado == "exited" and "(0)" not in c.status and "Exited" in c.status:
        ic, nome, cor = "✖", "erro", "error"
    return Text(f"{ic} {nome}", style=app.cor(cor))


class AbaContainers(AbaLista):
    NOME = "containers"
    COLUNAS = ("Estado", "Nome", "Imagem", "Portas", "CPU", "Memória")
    VAZIO = "Nenhum container ainda. Aperte n para rodar o primeiro a partir de uma imagem."
    RODAPE = ("acao('iniciar')", "acao('parar')", "acao('logs')", "acao('rodar')")
    ACOES = (("iniciar", "Iniciar (i)"), ("parar", "Parar (p)"), ("reiniciar", "Reiniciar (r)"), ("pausar", "Pausar (z)"),
             ("remover", "Remover (x)"), ("logs", "Logs (l)"), ("stats", "Stats (e)"), ("shell", "Shell (s)"), ("rodar", "Novo (n)"))
    BINDINGS = AbaLista.BINDINGS + [
        B("i", "iniciar", "Iniciar"), B("p", "parar", "Parar"), B("r", "reiniciar", "Reiniciar"), B("z", "pausar", "Pausar/retomar"),
        B("x", "remover", "Remover"), B("l", "logs", "Logs ao vivo"), B("e", "stats", "Estatísticas"),
        B("s", "shell", "Abrir shell no container"), B("n", "rodar", "Rodar container novo"),
        B("f", "filtro", "Alternar só rodando / todos"), B("g", "agrupar", "Alternar agrupar por projeto"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.so_rodando = False
        self.agrupar = True
        self.stats: dict[str, Estatistica] = {}
        self._buscando_stats = False
        self._mapa: dict[str, Container] = {}

    def barra(self) -> ComposeResult:
        yield Button("Mostrando: todos (f)", id="b-filtro", name="filtro")
        yield Button("Agrupar: sim (g)", id="b-agrupar", name="agrupar")

    def on_mount(self) -> None:  # o on_mount da base também roda (o Textual chama toda a cadeia)
        self.set_interval(4, self._stats)

    def buscar(self):
        return self.app.cliente.containers()

    def filtrar(self, dados, texto):
        r = [c for c in dados if (c.rodando or not self.so_rodando)]
        if texto:
            r = [c for c in r if texto in c.nome.lower() or texto in c.imagem.lower() or texto in c.projeto.lower()]
        return r

    def mapa(self):
        return self._mapa

    def linhas(self, dados):
        self._mapa = {c.id: c for c in dados}
        out = []

        def linha(c: Container, recuo=""):
            e = self.stats.get(c.id)
            cpu = Text(f"{e.cpu:.1f}%", justify="right") if e and c.estado == "running" else Text("-", style=self.app.cor("muted"))
            mem = Text(humano(e.mem_uso)) if e and c.estado == "running" else Text("-", style=self.app.cor("muted"))
            return (c.id, [celula_estado(self.app, c), Text(recuo + c.nome), Text(c.imagem, style=self.app.cor("muted")),
                           Text(c.portas), cpu, mem])

        grupos: dict[str, list[Container]] = {}
        for c in sorted(dados, key=lambda c: c.nome):
            grupos.setdefault(c.projeto if self.agrupar else "", []).append(c)
        for proj in sorted(grupos, key=lambda p: (p == "", p)):
            lista = grupos[proj]
            if self.agrupar and any(grupos):
                rot = f"▾ compose: {proj}  ({sum(c.estado == 'running' for c in lista)}/{len(lista)} rodando)" if proj else "▾ avulsos"
                out.append((f"g:{proj}", [Text(rot, style="bold " + self.app.cor("accent")), Text(""), Text(""), Text(""), Text(""), Text("")]))
                self._mapa[f"g:{proj}"] = None  # type: ignore[assignment]
            out += [linha(c, "  " if self.agrupar and any(grupos) else "") for c in lista]
        return out

    def selecionado(self):
        k = self.chave_atual()
        if k and k.startswith("g:"):
            self.app.notify("Essa linha é o título de um grupo. Selecione um container.", severity="warning")
            return None
        return self._mapa.get(k) if k else self.pedir_selecao()

    def depois_de_renderizar(self) -> None:
        self.query_one("#b-filtro", Button).label = "Mostrando: só rodando (f)" if self.so_rodando else "Mostrando: todos (f)"
        self.query_one("#b-agrupar", Button).label = f"Agrupar: {'sim' if self.agrupar else 'não'} (g)"

    def _stats(self) -> None:
        if self.app.aba_atual() != self.NOME or self._buscando_stats or len(self.app.screen_stack) > 1:
            return
        ids = [c.id for c in self.dados if c.estado == "running"]
        if not ids:
            return
        self._buscando_stats = True
        threading.Thread(target=self._thread_stats, args=(ids,), daemon=True).start()

    def _thread_stats(self, ids: list[str]) -> None:
        def um(i):
            try:
                return i, self.app.cliente.estatistica(i)
            except Exception:
                return i, None
        with ThreadPoolExecutor(max_workers=6) as ex:
            res = dict(ex.map(um, ids))
        try:
            self.app.call_from_thread(self._aplicar_stats, res)
        except Exception:
            self._buscando_stats = False

    def _aplicar_stats(self, res: dict) -> None:
        self._buscando_stats = False
        self.stats = {k: v for k, v in res.items() if v is not None}
        self.renderizar()

    def estado(self) -> dict:
        return {**super().estado(), "so_rodando": self.so_rodando, "agrupar": self.agrupar}

    def restaurar(self, d: dict) -> None:
        super().restaurar(d)
        if isinstance(d, dict):
            self.so_rodando = bool(d.get("so_rodando", False))
            self.agrupar = bool(d.get("agrupar", True))

    # ações
    def acao_filtro(self) -> None:
        self.so_rodando = not self.so_rodando
        self.renderizar()
        self.guardar()

    def acao_agrupar(self) -> None:
        self.agrupar = not self.agrupar
        self.renderizar()
        self.guardar()

    def _simples(self, metodo: str, verbo: str, apenas: str = "") -> None:
        c = self.selecionado()
        if c is None:
            return
        self.app.executar(f"{verbo} {c.nome}", getattr(self.app.cliente, metodo), c.id, ok=f"{c.nome}: {verbo.lower()} concluído")

    def acao_iniciar(self) -> None:
        c = self.selecionado()
        if c is not None and c.estado == "paused":
            return self._simples("retomar", "Retomar")
        self._simples("iniciar", "Iniciar")

    def acao_parar(self) -> None:
        self._simples("parar", "Parar")

    def acao_reiniciar(self) -> None:
        self._simples("reiniciar", "Reiniciar")

    def acao_pausar(self) -> None:
        c = self.selecionado()
        if c is None:
            return
        self._simples("retomar" if c.estado == "paused" else "pausar", "Retomar" if c.estado == "paused" else "Pausar")

    def acao_remover(self) -> None:
        c = self.selecionado()
        if c is None:
            return
        vols = ", ".join(v for v in self.app.volumes_do(c.id)) or "nenhum"
        itens = [f"{c.nome}  ({c.imagem}, {c.estado})"]
        aviso = "O container está rodando e será parado à força." if c.rodando else ""
        self.app.push_screen(
            Confirmar(f"Remover o container {c.nome}?", itens, total=f"Volumes ligados (não serão apagados): {vols}", aviso=aviso,
                      rotulo="Remover"),
            lambda ok: ok and self.app.executar(f"Remover {c.nome}", self.app.cliente.remover_container, c.id, c.rodando,
                                                ok=f"{c.nome} removido"))

    def acao_logs(self) -> None:
        c = self.selecionado()
        if c is not None:
            self.app.ver_logs(c.id, c.nome)

    def acao_stats(self) -> None:
        c = self.selecionado()
        if c is None:
            return
        if c.estado != "running":
            self.app.notify("O container não está rodando, então não há estatísticas.", severity="warning")
            return
        self.app.push_screen(TelaStats(self.app.cliente, c.id, c.nome))

    def acao_shell(self) -> None:
        c = self.selecionado()
        if c is None:
            return
        if c.estado != "running":
            self.app.notify("O container não está rodando. Inicie antes de abrir o shell.", severity="warning")
            return
        self.app.shell_no_container(c)

    def acao_rodar(self) -> None:
        self.app.rodar_novo()

    def acao_detalhes(self) -> None:
        c = self.selecionado()
        if c is None:
            return
        try:
            i = self.app.cliente.inspecionar(c.id)
        except Exception as e:
            self.app.notify(traduzir(e), severity="error")
            return
        cfg, host = i.get("Config", {}), i.get("HostConfig", {})
        linhas = [("Nome", c.nome), ("ID", c.id[:12]), ("Imagem", c.imagem), ("Estado", f"{c.estado} ({c.status})"),
                  ("Projeto", c.projeto or "nenhum"), ("Comando", " ".join(cfg.get("Cmd") or []) or "(padrão da imagem)"),
                  ("Reinício", (host.get("RestartPolicy") or {}).get("Name") or "não"), ("Portas", c.portas or "nenhuma"), ("", ""),
                  ("Volumes", ""), ]
        for m in i.get("Mounts") or []:
            linhas.append(("", f"{m.get('Name') or m.get('Source')} -> {m.get('Destination')}"))
        linhas += [("", ""), ("Redes", ", ".join((i.get("NetworkSettings") or {}).get("Networks", {}).keys()) or "nenhuma"), ("", ""),
                   ("Variáveis de ambiente", "")]
        from oma_docker.services.estado import SEGREDO
        for e in cfg.get("Env") or []:
            k, _, v = e.partition("=")
            linhas.append(("", f"{k}=" + ("•••• (oculto)" if SEGREDO.search(k) else v)))
        self.detalhes_texto(f"Container {c.nome}", linhas)


# --------------------------------------------------------------- Imagens

class AbaImagens(AbaLista):
    NOME = "imagens"
    COLUNAS = ("Imagem", "ID", "Tamanho", "Uso", "Criada")
    VAZIO = "Nenhuma imagem baixada. Aperte b para baixar uma."
    RODAPE = ("acao('rodar')", "acao('baixar')", "acao('apagar')")
    ACOES = (("rodar", "Rodar (n)"), ("baixar", "Baixar (b)"), ("apagar", "Apagar (x)"), ("detalhes", "Detalhes (Enter)"))
    BINDINGS = AbaLista.BINDINGS + [B("n", "rodar", "Rodar a partir da imagem"), B("b", "baixar", "Baixar imagem"), B("x", "apagar", "Apagar imagem"),
                                    B("u", "sem_uso", "Alternar só sem uso")]
    CADA = 3

    def __init__(self) -> None:
        super().__init__()
        self.so_sem_uso = False
        self._mapa: dict[str, Imagem] = {}

    def barra(self) -> ComposeResult:
        yield Button("Mostrando: todas (u)", id="b-sem_uso", name="sem_uso")

    def buscar(self):
        return self.app.cliente.imagens()

    def filtrar(self, dados, texto):
        r = [i for i in dados if not (self.so_sem_uso and i.em_uso)]
        return [i for i in r if texto in i.nome.lower() or texto in i.curto] if texto else r

    def mapa(self):
        return self._mapa

    def linhas(self, dados):
        self._mapa = {i.id: i for i in dados}
        out = []
        for i in sorted(dados, key=lambda i: i.nome):
            uso = Text("● " + ", ".join(i.usada_por[:2]), style=self.app.cor("success")) if i.em_uso else Text("○ sem uso", style=self.app.cor("muted"))
            out.append((i.id, [Text(i.nome), Text(i.curto, style=self.app.cor("muted")), Text(humano(i.tamanho), justify="right"), uso, Text(data(i.criada))]))
        return out

    def depois_de_renderizar(self) -> None:
        self.query_one("#b-sem_uso", Button).label = f"Mostrando: {'só sem uso' if self.so_sem_uso else 'todas'} (u)"

    def estado(self) -> dict:
        return {**super().estado(), "so_sem_uso": self.so_sem_uso}

    def restaurar(self, d: dict) -> None:
        super().restaurar(d)
        if isinstance(d, dict):
            self.so_sem_uso = bool(d.get("so_sem_uso", False))

    def acao_sem_uso(self) -> None:
        self.so_sem_uso = not self.so_sem_uso
        self.renderizar()
        self.guardar()

    def acao_rodar(self) -> None:
        i = self.pedir_selecao()
        if i is not None:
            self.app.rodar_novo(i.nome if i.tags else i.curto)

    def acao_baixar(self) -> None:
        self.app.baixar_imagem()

    def acao_apagar(self) -> None:
        i = self.pedir_selecao()
        if i is None:
            return
        aviso = f"Em uso por: {', '.join(i.usada_por)}. O Docker vai recusar." if i.em_uso else ""
        self.app.push_screen(
            Confirmar(f"Apagar a imagem {i.nome}?", [f"{i.nome}  ({i.curto}, {humano(i.tamanho)})"], total=f"Libera {humano(i.tamanho)}",
                      aviso=aviso, rotulo="Apagar"),
            lambda ok: ok and self.app.executar(f"Apagar {i.nome}", self.app.cliente.remover_imagem, i.id, ok=f"{i.nome} apagada"))

    def acao_detalhes(self) -> None:
        i = self.pedir_selecao()
        if i is not None:
            self.detalhes_texto(f"Imagem {i.nome}", [("Tags", ", ".join(i.tags) or "(sem tag)"), ("ID", i.id.removeprefix('sha256:')), ("Tamanho", humano(i.tamanho)),
                                                     ("Criada", data(i.criada)), ("Em uso por", ", ".join(i.usada_por) or "ninguém")])


# --------------------------------------------------------------- Volumes

class AbaVolumes(AbaLista):
    NOME = "volumes"
    COLUNAS = ("Nome", "Tipo", "Uso", "Tamanho", "Criado")
    VAZIO = "Nenhum volume. Aperte c para criar um."
    RODAPE = ("acao('criar')", "acao('apagar')", "acao('sem_uso')")
    ACOES = (("criar", "Criar (c)"), ("apagar", "Apagar (x)"), ("detalhes", "Detalhes (Enter)"))
    BINDINGS = AbaLista.BINDINGS + [B("c", "criar", "Criar volume"), B("x", "apagar", "Apagar volume"), B("u", "sem_uso", "Alternar só sem uso")]
    CADA = 3

    def __init__(self) -> None:
        super().__init__()
        self.so_sem_uso = False
        self._mapa: dict[str, Volume] = {}

    def barra(self) -> ComposeResult:
        yield Button("Mostrando: todos (u)", id="b-sem_uso", name="sem_uso")

    def buscar(self):
        return self.app.cliente.volumes()

    def filtrar(self, dados, texto):
        r = [v for v in dados if not (self.so_sem_uso and v.em_uso)]
        return [v for v in r if texto in v.nome.lower()] if texto else r

    def mapa(self):
        return self._mapa

    def linhas(self, dados):
        self._mapa = {v.nome: v for v in dados}
        out = []
        for v in sorted(dados, key=lambda v: (v.anonimo, v.nome)):
            uso = Text("● " + ", ".join(v.usado_por[:2]), style=self.app.cor("success")) if v.em_uso else Text("○ sem uso", style=self.app.cor("muted"))
            tipo = Text("sem nome", style=self.app.cor("warning")) if v.anonimo else Text("com nome")
            out.append((v.nome, [Text(v.nome_curto), tipo, uso, Text(humano(v.tamanho), justify="right"), Text(v.criado)]))
        return out

    def depois_de_renderizar(self) -> None:
        self.query_one("#b-sem_uso", Button).label = f"Mostrando: {'só sem uso' if self.so_sem_uso else 'todos'} (u)"

    def estado(self) -> dict:
        return {**super().estado(), "so_sem_uso": self.so_sem_uso}

    def restaurar(self, d: dict) -> None:
        super().restaurar(d)
        if isinstance(d, dict):
            self.so_sem_uso = bool(d.get("so_sem_uso", False))

    def acao_sem_uso(self) -> None:
        self.so_sem_uso = not self.so_sem_uso
        self.renderizar()
        self.guardar()

    def acao_criar(self) -> None:
        self.app.push_screen(Entrada("Criar volume", "Nome do volume", dica="meus_dados"),
                             lambda n: n and self.app.executar(f"Criar volume {n}", self.app.cliente.criar_volume, n, ok=f"Volume {n} criado"))

    def acao_apagar(self) -> None:
        v = self.pedir_selecao()
        if v is None:
            return
        reforco = ""
        if v.em_uso:
            reforco = f"O volume está em uso por {', '.join(v.usado_por)}. O Docker vai recusar."
        elif v.tamanho != 0:
            reforco = "Este volume tem dados (ou o tamanho é desconhecido). Apagar não tem volta."
        self.app.push_screen(
            Confirmar(f"Apagar o volume {v.nome_curto}?", [f"{v.nome}  ({humano(v.tamanho)})"], total=f"Libera {humano(max(v.tamanho, 0))}",
                      reforco=reforco, rotulo="Apagar mesmo assim" if reforco else "Apagar"),
            lambda ok: ok and self.app.executar(f"Apagar {v.nome_curto}", self.app.cliente.remover_volume, v.nome, ok=f"Volume {v.nome_curto} apagado"))

    def acao_detalhes(self) -> None:
        v = self.pedir_selecao()
        if v is not None:
            self.detalhes_texto(f"Volume {v.nome_curto}", [("Nome", v.nome), ("Driver", v.driver), ("Tamanho", humano(v.tamanho)), ("Criado", v.criado),
                                                           ("Usado por", ", ".join(v.usado_por) or "ninguém")])


# ----------------------------------------------------------------- Redes

class AbaRedes(AbaLista):
    NOME = "redes"
    COLUNAS = ("Nome", "Driver", "Escopo", "Sub-rede", "Containers")
    VAZIO = "Nenhuma rede. Aperte c para criar uma."
    RODAPE = ("acao('criar')", "acao('apagar')")
    ACOES = (("criar", "Criar (c)"), ("apagar", "Apagar (x)"), ("detalhes", "Detalhes (Enter)"))
    BINDINGS = AbaLista.BINDINGS + [B("c", "criar", "Criar rede"), B("x", "apagar", "Apagar rede")]
    CADA = 3

    def __init__(self) -> None:
        super().__init__()
        self._mapa: dict[str, Rede] = {}

    def buscar(self):
        return self.app.cliente.redes()

    def filtrar(self, dados, texto):
        return [r for r in dados if texto in r.nome.lower()] if texto else dados

    def mapa(self):
        return self._mapa

    def linhas(self, dados):
        self._mapa = {r.id: r for r in dados}
        return [(r.id, [Text(r.nome + ("  (padrão)" if r.padrao else "")), Text(r.driver), Text(r.escopo), Text(r.subnet),
                        Text(str(r.containers), style=self.app.cor("success" if r.containers else "muted"))]) for r in sorted(dados, key=lambda r: r.nome)]

    def acao_criar(self) -> None:
        self.app.push_screen(Entrada("Criar rede", "Nome da rede", dica="minha_rede"),
                             lambda n: n and self.app.executar(f"Criar rede {n}", self.app.cliente.criar_rede, n, ok=f"Rede {n} criada"))

    def acao_apagar(self) -> None:
        r = self.pedir_selecao()
        if r is None:
            return
        if r.padrao:
            self.app.notify("Redes padrão do Docker (bridge, host, none) não podem ser apagadas.", severity="warning")
            return
        aviso = f"Há {r.containers} container(s) conectados. O Docker vai recusar." if r.containers else ""
        self.app.push_screen(Confirmar(f"Apagar a rede {r.nome}?", [f"{r.nome}  ({r.driver}, {r.subnet or 'sem sub-rede'})"], aviso=aviso, rotulo="Apagar"),
                             lambda ok: ok and self.app.executar(f"Apagar rede {r.nome}", self.app.cliente.remover_rede, r.id, ok=f"Rede {r.nome} apagada"))

    def acao_detalhes(self) -> None:
        r = self.pedir_selecao()
        if r is not None:
            self.detalhes_texto(f"Rede {r.nome}", [("Nome", r.nome), ("ID", r.id[:12]), ("Driver", r.driver), ("Escopo", r.escopo),
                                                   ("Sub-rede", r.subnet or "nenhuma"), ("Containers", str(r.containers))])


# --------------------------------------------------------------- Compose

class AbaCompose(AbaLista):
    NOME = "compose"
    COLUNAS = ("Projeto", "Estado", "Serviços", "Pasta")
    VAZIO = "Nenhum projeto compose encontrado. Os projetos aparecem quando há containers criados por docker compose."
    RODAPE = ("acao('subir')", "acao('parar')", "acao('editar')", "acao('terminal')")
    ACOES = (("subir", "Subir (u)"), ("parar", "Parar (p)"), ("reiniciar", "Reiniciar (r)"), ("editar", "Editar compose (e)"),
             ("terminal", "Abrir terminal (t)"), ("containers", "Ver containers (c)"))
    BINDINGS = AbaLista.BINDINGS + [B("u", "subir", "Subir o projeto"), B("p", "parar", "Parar o projeto"), B("r", "reiniciar", "Reiniciar o projeto"),
                                    B("e", "editar", "Editar compose no nvim"), B("t", "terminal", "Abrir terminal na pasta"),
                                    B("c", "containers", "Ver containers do projeto")]

    def __init__(self) -> None:
        super().__init__()
        self._mapa: dict[str, ProjetoCompose] = {}

    def buscar(self):
        return projetos_de(self.app.cliente.containers())

    def filtrar(self, dados, texto):
        return [p for p in dados if texto in p.nome.lower()] if texto else dados

    def mapa(self):
        return self._mapa

    def linhas(self, dados):
        self._mapa = {p.nome: p for p in dados}
        out = []
        for p in dados:
            if p.rodando == 0:
                est = Text("○ parado", style=self.app.cor("muted"))
            elif p.rodando >= p.servicos:
                est = Text(f"● {p.rodando}/{p.servicos} rodando", style=self.app.cor("success"))
            else:
                est = Text(f"◐ {p.rodando}/{p.servicos} rodando", style=self.app.cor("warning"))
            out.append((p.nome, [Text(p.nome), est, Text(str(p.servicos)), Text(p.pasta, style=self.app.cor("muted"))]))
        return out

    def _acao_compose(self, acao: str, verbo: str) -> None:
        p = self.pedir_selecao()
        if p is not None:
            self.app.executar(f"{verbo} o projeto {p.nome}", self.app.cliente.compose, p.nome, acao, p.pasta, p.arquivos,
                              ok=f"Projeto {p.nome}: {verbo.lower()} concluído")

    def acao_subir(self) -> None:
        self._acao_compose("subir", "Subir")

    def acao_parar(self) -> None:
        self._acao_compose("parar", "Parar")

    def acao_reiniciar(self) -> None:
        self._acao_compose("reiniciar", "Reiniciar")

    def acao_editar(self) -> None:
        p = self.pedir_selecao()
        if p is not None:
            arq = p.arquivos[0] if p.arquivos else str(Path(p.pasta) / "compose.yml")
            self.app.editar_arquivo(arq, p.pasta, f"editar-{p.nome}")

    def acao_terminal(self) -> None:
        p = self.pedir_selecao()
        if p is not None:
            self.app.abrir_terminal(pasta=p.pasta or None)

    def acao_containers(self) -> None:
        p = self.pedir_selecao()
        if p is not None:
            self.app.ver_containers_de(p.nome)

    def acao_detalhes(self) -> None:
        p = self.pedir_selecao()
        if p is not None:
            self.detalhes_texto(f"Projeto {p.nome}", [("Projeto", p.nome), ("Pasta", p.pasta or "?"), ("Arquivos", ", ".join(p.arquivos) or "?"),
                                                      ("Serviços", str(p.servicos)), ("Rodando", str(p.rodando))])


# --------------------------------------------------------------- Limpeza

class AbaLimpeza(AbaLista):
    NOME = "limpeza"
    COLUNAS = ("", "Tipo", "Nome", "Tamanho", "Aviso")
    VAZIO = "Nada para limpar. Tudo o que existe está em uso."
    RODAPE = ("acao('marcar')", "acao('apagar')", "acao('todos')")
    ACOES = (("marcar", "Marcar (Espaço)"), ("todos", "Marcar tudo (a)"), ("nenhum", "Desmarcar (d)"), ("apagar", "Apagar marcados (x)"),
             ("cont", "Containers"), ("img", "Imagens"), ("volanon", "Volumes sem nome"), ("rede", "Redes"))
    BINDINGS = AbaLista.BINDINGS + [Binding("space", "acao('marcar')", "Marcar/desmarcar"), B("a", "todos", "Marcar tudo"),
                                    B("d", "nenhum", "Desmarcar tudo"), B("x", "apagar", "Apagar os marcados")]
    CADA = 3

    def __init__(self) -> None:
        super().__init__()
        self.marcados: set[str] = set()
        self._mapa: dict[str, ItemLimpeza] = {}

    def barra(self) -> ComposeResult:
        yield Static("", id="total")

    def buscar(self):
        c = self.app.cliente
        return itens_de_limpeza(c.containers(), c.imagens(), c.volumes(), c.redes())

    def chave(self, i: ItemLimpeza) -> str:
        return f"{i.tipo}:{i.id}"

    def filtrar(self, dados, texto):
        return [i for i in dados if texto in i.nome.lower() or texto in i.tipo] if texto else dados

    def mapa(self):
        return self._mapa

    def linhas(self, dados):
        self._mapa = {self.chave(i): i for i in dados}
        ordem = {"container": 0, "imagem": 1, "volume": 2, "rede": 3}
        out = []
        for i in sorted(dados, key=lambda i: (ordem[i.tipo], i.nome)):
            k = self.chave(i)
            marca = Text("[x]" if k in self.marcados else "[ ]", style=self.app.cor("accent") if k in self.marcados else self.app.cor("muted"))
            aviso = Text(i.aviso, style=self.app.cor("warning")) if i.aviso else Text("")
            out.append((k, [marca, Text(i.tipo), Text(i.nome), Text(humano(i.tamanho) if i.tamanho >= 0 else "-", justify="right"), aviso]))
        return out

    def depois_de_renderizar(self) -> None:
        vivos = {self.chave(i) for i in self.dados}
        self.marcados &= vivos
        sel = [i for i in self.dados if self.chave(i) in self.marcados]
        tam = sum(max(i.tamanho, 0) for i in sel)
        self.query_one("#total", Static).update(Text(f" Marcados: {len(sel)} de {len(self.dados)}   libera {humano(tam)}", style="bold"))

    def estado(self) -> dict:
        return {**super().estado(), "marcados": sorted(self.marcados)}

    def restaurar(self, d: dict) -> None:
        super().restaurar(d)
        if isinstance(d, dict) and isinstance(d.get("marcados"), list):
            self.marcados = {m for m in d["marcados"] if isinstance(m, str)}

    def acao_detalhes(self) -> None:
        self.acao_marcar()

    def acao_marcar(self) -> None:
        k = self.chave_atual()
        if k is None:
            return
        self.marcados ^= {k}
        self.renderizar()
        self.guardar()

    def _marcar_tipo(self, tipo: str, so_anonimos: bool = False) -> None:
        ks = {self.chave(i) for i in self.dados if i.tipo == tipo and (not so_anonimos or i.nome.endswith("(sem nome)"))}
        if not ks:
            self.app.notify("Não há itens dessa categoria para marcar.", severity="warning")
            return
        self.marcados = self.marcados | ks if not ks <= self.marcados else self.marcados - ks
        self.renderizar()
        self.guardar()

    def acao_cont(self) -> None:
        self._marcar_tipo("container")

    def acao_img(self) -> None:
        self._marcar_tipo("imagem")

    def acao_volanon(self) -> None:
        self._marcar_tipo("volume", True)

    def acao_rede(self) -> None:
        self._marcar_tipo("rede")

    def acao_todos(self) -> None:
        self.marcados = {self.chave(i) for i in self.filtrar(self.dados, self.texto_filtro())}
        self.renderizar()
        self.guardar()

    def acao_nenhum(self) -> None:
        self.marcados = set()
        self.renderizar()
        self.guardar()

    def acao_apagar(self) -> None:
        sel = [i for i in self.dados if self.chave(i) in self.marcados]
        if not sel:
            self.app.notify("Nada marcado. Marque itens com Espaço (ou clique em Marcar) e tente de novo.", severity="warning")
            return
        tam = sum(max(i.tamanho, 0) for i in sel)
        vols = [i for i in sel if i.tipo == "volume"]
        reforco = f"{len(vols)} volume(s) podem ter dados. Apagar não tem volta." if vols else ""
        linhas = [f"{i.tipo:<9} {i.nome}" + (f"  ({humano(i.tamanho)})" if i.tamanho >= 0 else "") for i in sel]
        self.app.push_screen(
            Confirmar(f"Apagar {len(sel)} item(ns)?", linhas, total=f"Libera cerca de {humano(tam)}", reforco=reforco,
                      rotulo="Apagar mesmo assim" if reforco else "Apagar"),
            lambda ok: ok and self.app.executar("Limpeza", self._apagar, sel, ok="Limpeza concluída"))

    def _apagar(self, itens: list[ItemLimpeza]) -> None:
        c = self.app.cliente
        falhas = []
        ordem = {"container": 0, "rede": 1, "imagem": 2, "volume": 3}
        for i in sorted(itens, key=lambda i: ordem[i.tipo]):
            try:
                {"container": lambda: c.remover_container(i.id, False), "imagem": lambda: c.remover_imagem(i.id),
                 "volume": lambda: c.remover_volume(i.id), "rede": lambda: c.remover_rede(i.id)}[i.tipo]()
                self.marcados.discard(self.chave(i))
            except Exception as e:
                falhas.append(f"{i.nome}: {traduzir(e)}")
        if falhas:
            from oma_docker.services.modelos import ErroDocker
            raise ErroDocker(f"{len(falhas)} item(ns) não saíram. " + falhas[0])


# -------------------------------------------------------------- Terminal

class AbaTerminal(AbaLista):
    NOME = "terminal"
    COLUNAS = ("Janela", "Programa", "Estado")
    VAZIO = "Nenhum terminal aberto. Aperte t para abrir um (ele continua vivo mesmo se você fechar o app)."
    RODAPE = ("acao('abrir')", "acao('nova')", "acao('editar')", "acao('encerrar')")
    ACOES = (("abrir", "Abrir terminal (t)"), ("nova", "Nova janela (n)"), ("editar", "Editar arquivo (e)"), ("encerrar", "Encerrar terminal (x)"))
    BINDINGS = AbaLista.BINDINGS + [B("t", "abrir", "Abrir/reanexar o terminal"), B("n", "nova", "Nova janela de shell"),
                                    B("e", "editar", "Editar um arquivo no nvim"), B("x", "encerrar", "Encerrar o terminal")]
    AJUDA_EXTRA = "[b]No terminal[/b]\n  Alt+q                volta ao oma-docker (o terminal segue vivo)\n  Alt+n / Alt+p        próxima / anterior janela"

    def buscar(self):
        t = self.app.tmux
        if not t.disponivel():
            raise RuntimeError("O tmux não está instalado. O terminal abre sem persistência (instale o pacote tmux).")
        return t.janelas()

    def filtrar(self, dados, texto):
        return [j for j in dados if texto in j.nome.lower()] if texto else dados

    def mapa(self):
        return {str(j.indice): j for j in self.dados}

    def linhas(self, dados):
        return [(str(j.indice), [Text(f"{j.indice} {j.nome}"), Text(j.comando), Text("● aberta" if j.ativa else "○ em segundo plano",
                                                                                      style=self.app.cor("success" if j.ativa else "muted"))]) for j in dados]

    def acao_abrir(self) -> None:
        self.app.abrir_terminal()

    def acao_detalhes(self) -> None:
        j = self.selecionado()
        if j is not None:
            self.app.abrir_terminal(janela=j.indice)

    def acao_nova(self) -> None:
        self.app.abrir_terminal(nova=True)

    def acao_editar(self) -> None:
        self.app.push_screen(Entrada("Editar arquivo", "Caminho do arquivo (abre no nvim)", dica="~/projeto/docker-compose.yml", ok="Abrir"),
                             lambda n: n and self.app.editar_arquivo(str(Path(n).expanduser()), str(Path(n).expanduser().parent), f"editar-{Path(n).name}"))

    def acao_encerrar(self) -> None:
        self.app.encerrar_terminal()


ABAS = (("resumo", "Resumo", AbaResumo), ("containers", "Containers", AbaContainers), ("imagens", "Imagens", AbaImagens),
        ("volumes", "Volumes", AbaVolumes), ("redes", "Redes", AbaRedes), ("compose", "Compose", AbaCompose),
        ("limpeza", "Limpeza", AbaLimpeza), ("terminal", "Terminal", AbaTerminal))
