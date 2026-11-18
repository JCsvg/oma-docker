"""Aplicativo Textual do oma-docker."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Header, TabbedContent, TabPane

from oma_docker import __version__, tema
from oma_docker.services.cliente import ClienteSDK
from oma_docker.services.erros import traduzir
from oma_docker.services.estado import Estado
from oma_docker.services.falso import ClienteFalso
from oma_docker.services.modelos import ErroDocker
from oma_docker.services.terminal import Tmux, comando_editar, comando_shell_container
from oma_docker.ui.abas import ABAS, AbaContainers, AbaResumo
from oma_docker.ui.abertura import Abertura
from oma_docker.ui.dialogos import Baixar, Confirmar, TelaLogs
from oma_docker.ui.formulario import FormularioRodar
from oma_docker.ui.navegacao import AjudaAba, RodapeEnxuto


class OmaDockerApp(App[None]):
    TITLE = "OMA DOCKER"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; color: $foreground; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0 1; }
    DataTable { height: 1fr; }
    #barra { height: 3; }
    #barra Input { width: 1fr; }
    #barra Button { margin-left: 1; }
    #acoes { height: 3; }
    #acoes Button { margin-right: 1; }
    DataTable > .datatable--cursor { background: $accent 28%; color: $foreground; text-style: bold; }
    DataTable:focus > .datatable--cursor { background: $accent 40%; color: $foreground; text-style: bold; }
    #vazio { height: 1fr; content-align: center middle; text-align: center; color: $text-muted; }
    #total { width: auto; margin-left: 1; content-align: left middle; height: 3; }
    #marca { text-style: bold; color: $accent; }
    #estado-docker { margin-bottom: 1; }
    #cartoes { grid-size: 3 2; grid-gutter: 1; grid-rows: 8; height: auto; margin-bottom: 1; }
    """
    BINDINGS = [
        Binding("q", "quit", "Sair"),
        *[Binding(str(n + 1), f"aba('{a[0]}')", a[1], show=False) for n, a in enumerate(ABAS)],
        Binding("alt+l,alt+right", "aba_relativa(1)", "Próxima tela", key_display="Alt+L", priority=True),
        Binding("alt+h,alt+left", "aba_relativa(-1)", "Tela anterior", key_display="Alt+H", priority=True),
        Binding("ctrl+right,ctrl+l", "botao(1)", "Próximo botão", key_display="Ctrl+→", priority=True),
        Binding("ctrl+left,ctrl+h", "botao(-1)", "Botão anterior", key_display="Ctrl+←", priority=True),
        Binding("ctrl+down,ctrl+j", "secao(1)", "Próxima seção", key_display="Ctrl+↓", priority=True),
        Binding("ctrl+up,ctrl+k", "secao(-1)", "Seção anterior", key_display="Ctrl+↑", priority=True),
        Binding("ctrl+@,ctrl+space,ctrl+at,f1", "ajuda_aba", "Ajuda", key_display="Ctrl+Espaço", priority=True),
        Binding("ctrl+enter", "botao_acionar", "Apertar botão", key_display="Ctrl+Enter", priority=True),
        Binding("escape", "voltar_foco", "Voltar à lista", show=False),
        Binding("f5", "recarregar", "Recarregar"),
    ]

    def __init__(self, cliente=None, demo: bool = False, estado: Estado | None = None, tmux: Tmux | None = None,
                 abertura: bool = True, anexador=None) -> None:
        super().__init__()
        self.demo = demo
        self.cliente = cliente or (ClienteFalso() if demo else ClienteSDK())
        self.estado = estado or Estado()
        self.tmux = tmux or Tmux(self.estado.pasta / "tmux.sock")
        self.com_abertura = abertura
        self.anexador = anexador or self._anexar_suspendendo
        self.paleta = tema.ler()
        self._aba_alvo = ""
        self._aba_alvo_em = 0.0
        self.pronto = False  # só depois de restaurar é que mudanças da UI viram contexto salvo
        self.salvo: dict = {}

    # ------------------------------------------------------------ montagem
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(initial="resumo", id="abas"):
            for n, (id_, rotulo, cls) in enumerate(ABAS):
                with TabPane(f"{n + 1} {rotulo}", id=id_):
                    yield cls()
        yield RodapeEnxuto()

    def on_mount(self) -> None:
        self.register_theme(tema.tema_textual("omarchy"))
        self.theme = "omarchy"
        self.sub_title = "Docker " + ("(demonstração)" if self.demo else "")
        self.estado.carregar()
        self.salvo = dict(self.estado.dados)  # o que estava salvo antes de qualquer evento da partida
        self.call_after_refresh(self._iniciar)

    def _iniciar(self) -> None:
        for id_, _, cls in ABAS:
            try:
                self.query_one(cls).restaurar(self.salvo.get(f"aba_{id_}", {}))
            except Exception:
                pass
        primeira = self.com_abertura and not self.estado.ja_abriu()
        aba = self.salvo.get("aba", "resumo")
        if aba in {a[0] for a in ABAS} and not primeira:
            self.query_one("#abas", TabbedContent).active = aba
        if primeira:
            self.estado.marcar_abertura()
            self.push_screen(Abertura(f"v{__version__}"), lambda _: self.call_after_refresh(self.focar_tabela))
        else:
            self.call_after_refresh(self.focar_tabela)
        self.pronto = True
        self.set_timer(0.3, self._terminar_restauracao)

    def _terminar_restauracao(self) -> None:
        if self.com_abertura and self.screen_stack[-1].__class__.__name__ == "Abertura":
            return
        lg = self.salvo.get("log")
        if isinstance(lg, dict) and lg.get("id") and len(self.screen_stack) == 1:
            self.ver_logs(str(lg["id"]), str(lg.get("nome", "")))
        elif self.salvo.get("form_aberto") and len(self.screen_stack) == 1:
            self.rodar_novo()

    def cor(self, nome: str) -> str:
        p = self.paleta
        return {"success": p["green"], "warning": p["yellow"], "error": p["red"], "accent": p["accent"],
                "muted": p.get("dark_foreground", p["muted"])}.get(nome, p["foreground"])

    # ------------------------------------------------------------ estado
    def guardar_aba(self, nome: str, d: dict) -> None:
        if self.pronto:
            self.estado.definir(f"aba_{nome}", d)

    def guardar_rascunho(self, d: dict) -> None:
        self.estado.definir("rascunho", d)

    # ------------------------------------------------------------ navegação
    def aba_atual(self) -> str:
        return self.query_one("#abas", TabbedContent).active

    def aba_widget(self):
        a = self.aba_atual()
        for id_, _, cls in ABAS:
            if id_ == a:
                return self.query_one(cls)
        return None

    def nav_da_aba(self):
        if len(self.screen_stack) > 1:
            return self.screen if hasattr(self.screen, "mover_secao") else None
        return self.aba_widget()

    def check_action(self, action: str, parameters):
        if action == "ajuda_aba":
            return self.nav_da_aba() is not None or isinstance(self.screen, AjudaAba)
        if action == "secao":
            return self.nav_da_aba() is not None
        return True

    def action_secao(self, passo: int) -> None:
        nav = self.nav_da_aba()
        if nav is not None:
            nav.mover_secao(passo)

    def action_ajuda_aba(self) -> None:
        if len(self.screen_stack) > 1:
            if isinstance(self.screen, AjudaAba):
                self.screen.dismiss(None)
            return
        nav = self.nav_da_aba()
        if nav is not None:
            self.push_screen(AjudaAba(nav.NOME.capitalize(), nav.texto_ajuda()))

    def action_voltar_foco(self) -> None:
        nav = self.nav_da_aba()
        if nav is not None and len(self.screen_stack) == 1:
            nav.focar_entrada()

    def action_aba(self, aba: str) -> None:
        if len(self.screen_stack) > 1 or aba not in {a[0] for a in ABAS}:
            return
        self._ir_para(aba)

    def _ir_para(self, aba: str) -> None:
        self._aba_alvo, self._aba_alvo_em = aba, time.monotonic()
        self.query_one("#abas", TabbedContent).active = aba
        self.call_after_refresh(self.focar_tabela)

    def action_aba_relativa(self, passo: int) -> None:
        if len(self.screen_stack) > 1:
            return
        ordem = [a[0] for a in ABAS]
        base = self._aba_alvo or self.aba_atual()
        self._ir_para(ordem[(ordem.index(base) + passo) % len(ordem)])

    def _botoes(self) -> list[Button]:
        raiz = self.screen if len(self.screen_stack) > 1 else self.aba_widget()
        if raiz is None:
            return []
        nav = self.nav_da_aba()
        fileira = nav.fileira() if nav is not None else []
        if fileira:
            return [w for w in fileira if w.focusable]
        return [b for b in raiz.query(Button) if b.display and not b.disabled and b.region.area > 0]

    def action_botao(self, passo: int) -> None:
        botoes = self._botoes()
        if not botoes:
            return
        atual = self.focused
        if atual in botoes:
            botoes[(botoes.index(atual) + passo) % len(botoes)].focus()
        else:
            botoes[0 if passo > 0 else -1].focus()

    def action_botao_acionar(self) -> None:
        if isinstance(self.focused, Button) and not self.focused.disabled:
            self.focused.press()

    def focar_tabela(self) -> None:
        a = self.aba_widget()
        if a is not None:
            a.focar_entrada()

    def action_recarregar(self) -> None:
        a = self.aba_widget()
        if a is not None:
            a.recarregar()

    @on(TabbedContent.TabActivated)
    def _aba_mudou(self) -> None:
        ativa = self.aba_atual()
        if self._aba_alvo and ativa != self._aba_alvo and time.monotonic() - self._aba_alvo_em < 0.6:
            self.query_one("#abas", TabbedContent).active = self._aba_alvo
            return
        self._aba_alvo = ativa
        if self.pronto:
            self.estado.definir("aba", ativa)
        a = self.aba_widget()
        if a is not None:
            a.recarregar()
        self.call_after_refresh(self.focar_tabela)

    def ver_containers_de(self, projeto: str) -> None:
        from textual.widgets import Input
        aba = self.query_one(AbaContainers)
        aba.query_one("#filtro", Input).value = projeto
        self.action_aba("containers")

    def pop_screen(self):
        r = super().pop_screen()
        if len(self.screen_stack) == 1:
            self.call_after_refresh(self.focar_tabela)
        return r

    # ------------------------------------------------------------ Docker
    def executar(self, descricao: str, func, *args, ok: str = "", depois=None) -> None:
        """Roda func(*args) numa thread. Erros viram aviso em português; no fim recarrega a tela."""
        def trabalho() -> None:
            try:
                func(*args)
                erro = ""
            except Exception as e:
                erro = traduzir(e)
            try:
                self.call_from_thread(self._fim_acao, descricao, erro, ok, depois)
            except Exception:
                pass
        threading.Thread(target=trabalho, daemon=True).start()

    def _fim_acao(self, descricao: str, erro: str, ok: str, depois) -> None:
        if erro:
            self.notify(f"{descricao}: {erro}", severity="error", timeout=8)
        elif ok:
            self.notify(ok)
        if depois:
            depois(not erro)
        for id_, _, cls in ABAS:
            try:
                w = self.query_one(cls)
                if id_ == self.aba_atual() or id_ in ("resumo", "containers"):
                    w.recarregar()
            except Exception:
                pass

    def volumes_do(self, cid: str) -> list[str]:
        try:
            return [m.get("Name") or m.get("Source", "") for m in self.cliente.inspecionar(cid).get("Mounts") or []]
        except Exception:
            return []

    def ver_logs(self, cid: str, nome: str) -> None:
        self.estado.definir("log", {"id": cid, "nome": nome})
        self.push_screen(TelaLogs(self.cliente, cid, nome))

    def rodar_novo(self, imagem: str = "") -> None:
        self.estado.definir("form_aberto", True)

        def fim(pedido) -> None:
            if pedido is None:
                return
            def depois(ok: bool) -> None:
                if ok:
                    self.estado.definir("rascunho", None)
                    if not pedido.segundo_plano:
                        self.ver_logs(pedido.nome or pedido.imagem, pedido.nome or pedido.imagem)
            self.executar(f"Rodar {pedido.imagem}", self.cliente.rodar, pedido, ok=f"{pedido.imagem} rodando", depois=depois)
        self.push_screen(FormularioRodar(imagem, self.estado.obter("rascunho", {})), fim)

    def baixar_imagem(self) -> None:
        self.push_screen(Baixar(self.cliente), lambda ref: self._fim_acao("Baixar", "", f"{ref} baixada" if ref else "", None))

    # ------------------------------------------------------------ terminal
    def _anexar_suspendendo(self, argv: list[str]) -> None:
        with self.suspend():
            subprocess.run(argv)

    def abrir_terminal(self, janela: int | None = None, pasta: str | None = None, nova: bool = False,
                       comando: str | None = None, nome: str = "shell") -> None:
        if not self.tmux.disponivel():
            self.notify("O tmux não está instalado: o terminal abre, mas não continua vivo ao fechar o app.", severity="warning", timeout=8)
            self.anexador([os.environ.get("SHELL", "/bin/sh")] if not comando else ["sh", "-c", comando])
            return
        try:
            if comando or nova:
                self.tmux.nova_janela(nome, comando, pasta)
            else:
                self.tmux.garantir(pasta)
            if janela is not None:
                self.tmux.selecionar(janela)
        except ErroDocker as e:
            self.notify(str(e), severity="error")
            return
        self.anexador(self.tmux.argv_anexar())
        self.action_recarregar()

    def shell_no_container(self, c) -> None:
        self.abrir_terminal(comando=comando_shell_container(c.id), nome=f"sh-{c.nome}")

    def editar_arquivo(self, arquivo: str, pasta: str, nome: str) -> None:
        if not Path(arquivo).is_file():
            self.notify(f"Arquivo não encontrado: {arquivo}", severity="error")
            return
        if self.tmux.disponivel():
            existente = next((j for j in self.tmux.janelas() if j.nome == nome[:30]), None)
            if existente is not None:
                self.abrir_terminal(janela=existente.indice)
                return
        self.abrir_terminal(comando=comando_editar(arquivo), nome=nome, pasta=pasta if Path(pasta).is_dir() else None)

    def encerrar_terminal(self) -> None:
        if not self.tmux.ativo():
            self.notify("Não há terminal aberto.", severity="warning")
            return
        aviso = "Há um editor (nvim) aberto. Alterações não salvas serão perdidas." if self.tmux.tem_editor() else ""
        n = len(self.tmux.janelas())
        def fim(ok):
            if ok:
                self.tmux.encerrar()
                self.notify("Terminal encerrado.")
                self.action_recarregar()
        self.push_screen(Confirmar("Encerrar o terminal?", [f"{n} janela(s) serão fechadas, com tudo o que roda nelas."], aviso=aviso,
                                   rotulo="Encerrar"), fim)

    # ------------------------------------------------------------ saída
    async def action_quit(self) -> None:
        self.estado.salvar()
        self.exit()


def main() -> None:
    p = argparse.ArgumentParser(prog="oma-docker", description="Gerenciador de Docker em TUI")
    p.add_argument("--demo", action="store_true", help="usa dados de exemplo, sem falar com o Docker")
    p.add_argument("--version", action="version", version=f"oma-docker {__version__}")
    a = p.parse_args()
    OmaDockerApp(demo=a.demo).run()


if __name__ == "__main__":
    main()
