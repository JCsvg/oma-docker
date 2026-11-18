"""Diálogos: confirmar, entrada de texto, detalhes, logs ao vivo, estatísticas e baixar imagem."""

from __future__ import annotations

import threading
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Static

from oma_docker.services.erros import traduzir
from oma_docker.services.modelos import humano
from oma_docker.ui.navegacao import NavegacaoMixin

CSS_CAIXA = """
{n} { align: center middle; }
{n} #caixa { width: 74; height: auto; max-height: 92%; background: $surface; border: round $accent; padding: 1 2; }
{n} .titulo { text-style: bold; color: $accent; margin-bottom: 1; }
{n} .aviso { color: $warning; text-style: bold; }
{n} .perigo { color: $error; text-style: bold; }
{n} .mudo { color: $text-muted; }
{n} .botoes { height: 3; margin-top: 1; }
{n} .botoes Button { margin-right: 2; }
"""


class Confirmar(NavegacaoMixin, ModalScreen[bool]):
    """Pede confirmação mostrando o que será afetado. Esc cancela. O foco começa em Cancelar."""

    DEFAULT_CSS = CSS_CAIXA.replace("{n}", "Confirmar") + "Confirmar #lista { max-height: 14; margin-bottom: 1; }"
    BINDINGS = [Binding("escape", "cancelar", "Cancelar", show=False)]

    def __init__(self, titulo: str, itens: list[str], total: str = "", aviso: str = "", reforco: str = "",
                 rotulo: str = "Confirmar", perigoso: bool = True) -> None:
        super().__init__()
        self.titulo, self.itens, self.total, self.aviso, self.reforco = titulo, itens, total, aviso, reforco
        self.rotulo, self.perigoso = rotulo, perigoso

    def compose(self) -> ComposeResult:
        with Vertical(id="caixa"):
            yield Label(Text(self.titulo), classes="titulo")
            with VerticalScroll(id="lista"):
                for i in self.itens:
                    yield Static(Text("  " + i))
            if self.total:
                yield Static(Text(self.total, style="bold"))
            if self.aviso:
                yield Static(Text(self.aviso), classes="aviso")
            if self.reforco:
                yield Static(Text("ATENÇÃO: " + self.reforco), classes="perigo")
            with Horizontal(classes="botoes"):
                yield Button("Cancelar", id="cancelar")
                yield Button(self.rotulo, id="ok", variant="error" if self.perigoso else "primary")

    def on_mount(self) -> None:
        self.query_one("#cancelar" if self.perigoso else "#ok").focus()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.dismiss(ev.button.id == "ok")

    def action_cancelar(self) -> None:
        self.dismiss(False)


class Entrada(NavegacaoMixin, ModalScreen[str | None]):
    DEFAULT_CSS = CSS_CAIXA.replace("{n}", "Entrada")
    BINDINGS = [Binding("escape", "cancelar", "Cancelar", show=False)]

    def __init__(self, titulo: str, rotulo: str, valor: str = "", dica: str = "", ok: str = "Criar") -> None:
        super().__init__()
        self.titulo, self.rotulo, self.valor, self.dica, self.ok = titulo, rotulo, valor, dica, ok

    def compose(self) -> ComposeResult:
        with Vertical(id="caixa"):
            yield Label(Text(self.titulo), classes="titulo")
            yield Label(Text(self.rotulo))
            yield Input(self.valor, placeholder=self.dica, id="campo")
            yield Static("", id="erro", classes="perigo")
            with Horizontal(classes="botoes"):
                yield Button("Cancelar", id="cancelar")
                yield Button(self.ok, id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#campo").focus()

    def _enviar(self) -> None:
        v = self.query_one("#campo", Input).value.strip()
        if not v:
            self.query_one("#erro", Static).update("Preencha o campo.")
            return
        self.dismiss(v)

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self._enviar()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "ok":
            self._enviar()
        else:
            self.dismiss(None)

    def action_cancelar(self) -> None:
        self.dismiss(None)


class Detalhes(NavegacaoMixin, ModalScreen[None]):
    DEFAULT_CSS = CSS_CAIXA.replace("{n}", "Detalhes") + "Detalhes #caixa { width: 90; height: 90%; } Detalhes #corpo { height: 1fr; }"
    BINDINGS = [Binding("escape,q", "fechar", "Fechar", show=False)]

    def __init__(self, titulo: str, linhas: list[tuple[str, str]]) -> None:
        super().__init__()
        self.titulo, self.linhas = titulo, linhas

    def compose(self) -> ComposeResult:
        with Vertical(id="caixa"):
            yield Label(Text(self.titulo), classes="titulo")
            with VerticalScroll(id="corpo"):
                for k, v in self.linhas:
                    t = Text()
                    if v == "" and k:
                        t.append(k, style="bold")
                    else:
                        t.append(f"{k:<14}", style="dim")
                        t.append(v)
                    yield Static(t)
            with Horizontal(classes="botoes"):
                yield Button("Fechar", id="fechar", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#fechar").focus()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.dismiss(None)

    def action_fechar(self) -> None:
        self.dismiss(None)


class TelaLogs(NavegacaoMixin, ModalScreen[None]):
    """Logs que seguem ao vivo. Pausar congela a tela (as linhas novas esperam na fila)."""

    DEFAULT_CSS = CSS_CAIXA.replace("{n}", "TelaLogs") + "TelaLogs #caixa { width: 96%; height: 94%; } TelaLogs RichLog { height: 1fr; border: tall $panel; }"
    BINDINGS = [Binding("escape,q", "fechar", "Fechar", show=False), Binding("space", "alternar", "Pausar/seguir", show=False)]

    def __init__(self, cliente, id: str, nome: str) -> None:
        super().__init__()
        self.cliente, self.cid, self.nome = cliente, id, nome
        self.parar = threading.Event()
        self.pausado = False
        self.fila: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="caixa"):
            yield Label(Text(f"Logs de {self.nome} (ao vivo)"), classes="titulo")
            yield RichLog(id="log", wrap=True, markup=False, max_lines=5000, auto_scroll=True)
            with Horizontal(classes="botoes"):
                yield Button("Pausar", id="alternar")
                yield Button("Limpar", id="limpar")
                yield Button("Fechar", id="fechar", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#fechar").focus()
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self) -> None:
        try:
            for linha in self.cliente.logs(self.cid, True, 200):
                if self.parar.is_set():
                    return
                self.app.call_from_thread(self._linha, linha)
        except Exception as e:
            if not self.parar.is_set():
                try:
                    self.app.call_from_thread(self._linha, "[erro] " + traduzir(e))
                except Exception:
                    pass

    def _linha(self, linha: str) -> None:
        if self.pausado:
            self.fila.append(linha)
        else:
            self.query_one("#log", RichLog).write(Text(linha))

    def action_alternar(self) -> None:
        self.pausado = not self.pausado
        b = self.query_one("#alternar", Button)
        b.label = "Seguir" if self.pausado else "Pausar"
        if not self.pausado:
            log = self.query_one("#log", RichLog)
            for l in self.fila:
                log.write(Text(l))
            self.fila.clear()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "alternar":
            self.action_alternar()
        elif ev.button.id == "limpar":
            self.query_one("#log", RichLog).clear()
        else:
            self.action_fechar()

    def action_fechar(self) -> None:
        self.parar.set()
        self.app.estado.definir("log", None)  # fechar de propósito apaga; o app fechar não
        self.dismiss(None)


class TelaStats(NavegacaoMixin, ModalScreen[None]):
    DEFAULT_CSS = CSS_CAIXA.replace("{n}", "TelaStats")
    BINDINGS = [Binding("escape,q", "fechar", "Fechar", show=False)]

    def __init__(self, cliente, id: str, nome: str) -> None:
        super().__init__()
        self.cliente, self.cid, self.nome = cliente, id, nome
        self.vivo = True
        self.cargas = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="caixa"):
            yield Label(Text(f"Estatísticas de {self.nome}"), classes="titulo")
            yield Static("Lendo...", id="corpo")
            with Horizontal(classes="botoes"):
                yield Button("Fechar", id="fechar", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#fechar").focus()
        self._pedir()
        self.set_interval(2, self._pedir)

    def _pedir(self) -> None:
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self) -> None:
        try:
            s = self.cliente.estatistica(self.cid)
            pct = (s.mem_uso / s.mem_limite * 100) if s.mem_limite else 0
            t = Text()
            for k, v in (("CPU", f"{s.cpu:.1f}%"), ("Memória", f"{humano(s.mem_uso)} de {humano(s.mem_limite)} ({pct:.1f}%)"),
                         ("Rede", f"recebido {humano(s.rede_rx)}, enviado {humano(s.rede_tx)}"),
                         ("Disco", f"lido {humano(s.bloco_leitura)}, escrito {humano(s.bloco_escrita)}")):
                t.append(f"{k:<10}", style="dim")
                t.append(v + "\n")
        except Exception as e:
            t = Text(traduzir(e), style="bold red")
        if self.vivo:
            try:
                self.app.call_from_thread(self._mostrar, t)
            except Exception:
                pass

    def _mostrar(self, t: Text) -> None:
        self.cargas += 1
        self.query_one("#corpo", Static).update(t)

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.action_fechar()

    def action_fechar(self) -> None:
        self.vivo = False
        self.dismiss(None)


class Baixar(NavegacaoMixin, ModalScreen[str | None]):
    """Pede o nome da imagem e baixa mostrando o progresso."""

    DEFAULT_CSS = CSS_CAIXA.replace("{n}", "Baixar")
    BINDINGS = [Binding("escape", "cancelar", "Cancelar", show=False)]

    def __init__(self, cliente) -> None:
        super().__init__()
        self.cliente = cliente
        self.ocupado = False
        self.baixou = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="caixa"):
            yield Label("Baixar imagem", classes="titulo")
            yield Label("Nome da imagem (ex.: nginx:1.27 ou ubuntu)")
            yield Input(placeholder="nome:tag", id="campo")
            yield Static("", id="progresso", classes="mudo")
            with Horizontal(classes="botoes"):
                yield Button("Fechar", id="cancelar")
                yield Button("Baixar", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#campo").focus()

    def _iniciar(self) -> None:
        ref = self.query_one("#campo", Input).value.strip()
        if not ref or self.ocupado:
            if not ref:
                self.query_one("#progresso", Static).update(Text("Digite o nome da imagem.", style="bold red"))
            return
        self.ocupado = True
        self.query_one("#ok", Button).disabled = True
        threading.Thread(target=self._baixar, args=(ref,), daemon=True).start()

    def _baixar(self, ref: str) -> None:
        def prog(t: str) -> None:
            self.app.call_from_thread(self._texto, Text(t))
        try:
            self.cliente.baixar_imagem(ref, prog)
            self.app.call_from_thread(self._fim, ref, None)
        except Exception as e:
            self.app.call_from_thread(self._fim, ref, traduzir(e))

    def _texto(self, t: Text) -> None:
        self.query_one("#progresso", Static).update(t)

    def _fim(self, ref: str, erro: str | None) -> None:
        self.ocupado = False
        self.query_one("#ok", Button).disabled = False
        if erro:
            self._texto(Text(erro, style="bold red"))
        else:
            self.baixou = ref
            self._texto(Text(f"Pronto: {ref} baixada.", style="bold green"))

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self._iniciar()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "ok":
            self._iniciar()
        else:
            self.dismiss(self.baixou or None)

    def action_cancelar(self) -> None:
        self.dismiss(self.baixou or None)
