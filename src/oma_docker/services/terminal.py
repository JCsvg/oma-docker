"""Terminal persistente: um servidor tmux dedicado, separado do tmux pessoal.

O socket fica em $XDG_RUNTIME_DIR/oma-docker/tmux.sock. O servidor sobrevive ao
fechar o app e a janela do terminal, e some quando o PC desliga.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from oma_docker.services.estado import pasta_padrao
from oma_docker.services.modelos import ErroDocker

SESSAO = "oma-docker"
CONF = Path(__file__).resolve().parent.parent / "data" / "tmux.conf"


@dataclass
class Janela:
    indice: int
    nome: str
    comando: str
    ativa: bool


class Tmux:
    def __init__(self, socket: Path | None = None, conf: Path = CONF) -> None:
        self.socket = socket or (pasta_padrao() / "tmux.sock")
        self.conf = conf

    def disponivel(self) -> bool:
        return shutil.which("tmux") is not None

    def _base(self) -> list[str]:
        return ["tmux", "-S", str(self.socket), "-f", str(self.conf)]

    def _rodar(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([*self._base(), *args], capture_output=True, text=True, timeout=10)

    def ativo(self) -> bool:
        if not self.disponivel() or not self.socket.exists():
            return False
        return self._rodar("has-session", "-t", SESSAO).returncode == 0

    def garantir(self, pasta: str | None = None) -> None:
        """Cria a sessão se ainda não existe (com um shell). Sem efeito se já existe."""
        if not self.disponivel():
            raise ErroDocker("O tmux não está instalado, então o terminal não fica vivo ao fechar o app.")
        if self.ativo():
            return
        self.socket.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.socket.parent, 0o700)
        r = self._rodar("new-session", "-d", "-s", SESSAO, "-n", "shell", "-c", pasta or os.path.expanduser("~"))
        if r.returncode != 0:
            raise ErroDocker("Não consegui iniciar o terminal: " + (r.stderr.strip() or "erro do tmux"))

    def nova_janela(self, nome: str, comando: str | list[str] | None = None, pasta: str | None = None) -> None:
        self.garantir(pasta)
        args = ["new-window", "-t", SESSAO + ":", "-n", nome[:30]]
        if pasta:
            args += ["-c", pasta]
        if comando:
            args.append(comando if isinstance(comando, str) else shlex.join(comando))
        r = self._rodar(*args)
        if r.returncode != 0:
            raise ErroDocker("Não consegui abrir a janela: " + (r.stderr.strip() or "erro do tmux"))

    def janelas(self) -> list[Janela]:
        if not self.ativo():
            return []
        r = self._rodar("list-windows", "-t", SESSAO, "-F", "#{window_index}\t#{window_name}\t#{pane_current_command}\t#{window_active}")
        saida = []
        for l in r.stdout.splitlines():
            p = l.split("\t")
            if len(p) == 4:
                saida.append(Janela(int(p[0]), p[1], p[2], p[3] == "1"))
        return saida

    def selecionar(self, indice: int) -> None:
        self._rodar("select-window", "-t", f"{SESSAO}:{indice}")

    def argv_anexar(self) -> list[str]:
        return [*self._base(), "attach-session", "-t", SESSAO]

    def tem_editor(self) -> bool:
        return any(j.comando in ("nvim", "vim", "vi") for j in self.janelas())

    def enviar(self, janela: int, texto: str) -> None:
        self._rodar("send-keys", "-t", f"{SESSAO}:{janela}", texto, "Enter")

    def encerrar(self) -> None:
        if self.socket.exists():
            self._rodar("kill-server")
            try:
                self.socket.unlink()
            except OSError:
                pass


def comando_editar(arquivo: str) -> str:
    return f"nvim {shlex.quote(arquivo)}"


def comando_shell_container(id: str) -> str:
    return f"docker exec -it {shlex.quote(id)} sh -c 'command -v bash >/dev/null && exec bash || exec sh'"
