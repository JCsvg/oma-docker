"""Formulário para rodar um container novo a partir de uma imagem."""

from __future__ import annotations

import shlex

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

from oma_docker.services.erros import traduzir
from oma_docker.services.estado import limpar_ambiente
from oma_docker.services.modelos import PedidoRodar
from oma_docker.ui.dialogos import CSS_CAIXA
from oma_docker.ui.navegacao import NavegacaoMixin

CAMPOS = ("imagem", "nome", "portas", "ambiente", "volumes", "comando")


class FormularioRodar(NavegacaoMixin, ModalScreen["PedidoRodar | None"]):
    DEFAULT_CSS = CSS_CAIXA.replace("{n}", "FormularioRodar") + """
    FormularioRodar #caixa { width: 90; max-height: 98%; }
    FormularioRodar #campos { height: auto; max-height: 12; }
    FormularioRodar .linha { height: 1; }
    FormularioRodar .linha Label { width: 14; }
    FormularioRodar .linha Input { width: 1fr; background: $panel; }
    FormularioRodar Checkbox { height: 1; }
    FormularioRodar .botoes { margin-top: 1; }
    """
    BINDINGS = [Binding("escape", "cancelar", "Cancelar", show=False)]

    def __init__(self, imagem: str = "", rascunho: dict | None = None) -> None:
        super().__init__()
        self.rascunho = dict(rascunho or {})
        if imagem:
            self.rascunho["imagem"] = imagem

    def compose(self) -> ComposeResult:
        r = self.rascunho
        with Vertical(id="caixa"):
            yield Label("Rodar um container novo", classes="titulo")
            with VerticalScroll(id="campos"):
                for id_, rot, dica in (("imagem", "Imagem *", "nginx:1.27"), ("nome", "Nome", "meu-nginx (opcional)"),
                                       ("portas", "Portas", "host:container  ex.: 8080:80 5432:5432"),
                                       ("ambiente", "Variáveis", "CHAVE=valor  ex.: MODO=teste (aspas se tiver espaço)"),
                                       ("volumes", "Volumes", "origem:destino  ex.: meu_volume:/dados"),
                                       ("comando", "Comando", "opcional  ex.: sleep 3600")):
                    with Horizontal(classes="linha"):
                        yield Label(rot)
                        yield Input(r.get(id_, ""), placeholder=dica, id=id_, compact=True)
                yield Checkbox("Reiniciar sempre (restart always)", r.get("reiniciar", False), id="reiniciar", compact=True)
                yield Checkbox("Em segundo plano (senão abre os logs)", r.get("segundo_plano", True), id="segundo_plano", compact=True)
            yield Static("", id="erro", classes="perigo")
            with Horizontal(classes="botoes"):
                yield Button("Cancelar", id="cancelar")
                yield Button("Rodar", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#imagem" if not self.rascunho.get("imagem") else "#nome").focus()

    def valores(self) -> dict:
        d = {c: self.query_one(f"#{c}", Input).value for c in CAMPOS}
        d["reiniciar"] = self.query_one("#reiniciar", Checkbox).value
        d["segundo_plano"] = self.query_one("#segundo_plano", Checkbox).value
        return d

    def _guardar(self) -> None:
        d = self.valores()
        try:
            d["ambiente"] = shlex.join(limpar_ambiente(shlex.split(d["ambiente"])))
        except ValueError:
            d["ambiente"] = ""
        guardar = getattr(self.app, "guardar_rascunho", None)
        if guardar:
            guardar(d)

    def on_input_changed(self, ev: Input.Changed) -> None:
        self._guardar()

    def on_checkbox_changed(self, ev: Checkbox.Changed) -> None:
        self._guardar()

    def _pedido(self) -> PedidoRodar:
        d = self.valores()
        if not d["imagem"].strip():
            raise ValueError("Informe a imagem.")
        try:
            portas, amb, vols = shlex.split(d["portas"]), shlex.split(d["ambiente"]), shlex.split(d["volumes"])
        except ValueError:
            raise ValueError("Aspas sem fechar em algum campo.") from None
        return PedidoRodar(imagem=d["imagem"].strip(), nome=d["nome"].strip(), portas=portas, ambiente=amb, volumes=vols,
                           comando=d["comando"].strip(), reiniciar=d["reiniciar"], segundo_plano=d["segundo_plano"])

    def _fechar_estado(self) -> None:
        self.app.estado.definir("form_aberto", False)

    def _enviar(self) -> None:
        try:
            pedido = self._pedido()
            self._fechar_estado()
            self.dismiss(pedido)
        except Exception as e:
            self.query_one("#erro", Static).update(Text(traduzir(e) if not isinstance(e, ValueError) else str(e)))

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self._enviar()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "ok":
            self._enviar()
        else:
            self._fechar_estado()
            self.dismiss(None)

    def action_cancelar(self) -> None:
        self._fechar_estado()
        self.dismiss(None)
