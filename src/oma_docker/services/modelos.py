"""Modelos simples, independentes do SDK, usados pela UI e pelos serviços."""

from __future__ import annotations

from dataclasses import dataclass, field

TESTE_ROTULO = "oma-docker-test"


@dataclass
class Container:
    id: str
    nome: str
    imagem: str
    estado: str  # running, exited, paused, created, restarting, dead
    status: str = ""  # texto do Docker, ex.: "Up 2 hours"
    portas: str = ""  # "8080->80/tcp, 3306/tcp"
    projeto: str = ""  # projeto compose, se houver
    servico: str = ""
    criado: float = 0.0
    rotulos: dict[str, str] = field(default_factory=dict)

    @property
    def rodando(self) -> bool:
        return self.estado in ("running", "restarting", "paused")


@dataclass
class Estatistica:
    cpu: float = 0.0  # porcentagem
    mem_uso: int = 0  # bytes
    mem_limite: int = 0
    rede_rx: int = 0
    rede_tx: int = 0
    bloco_leitura: int = 0
    bloco_escrita: int = 0


@dataclass
class Imagem:
    id: str
    tags: list[str]
    tamanho: int
    criada: float
    em_uso: bool = False
    usada_por: list[str] = field(default_factory=list)

    @property
    def nome(self) -> str:
        return self.tags[0] if self.tags else "<sem tag>"

    @property
    def curto(self) -> str:
        return self.id.removeprefix("sha256:")[:12]


@dataclass
class Volume:
    nome: str
    driver: str = "local"
    tamanho: int = -1  # -1: desconhecido
    em_uso: bool = False
    usado_por: list[str] = field(default_factory=list)
    criado: str = ""
    rotulos: dict[str, str] = field(default_factory=dict)

    @property
    def anonimo(self) -> bool:
        n = self.nome
        return len(n) == 64 and all(c in "0123456789abcdef" for c in n)

    @property
    def nome_curto(self) -> str:
        return self.nome[:12] + "…" if self.anonimo else self.nome


@dataclass
class Rede:
    id: str
    nome: str
    driver: str = "bridge"
    escopo: str = "local"
    subnet: str = ""
    containers: int = 0

    @property
    def padrao(self) -> bool:
        return self.nome in ("bridge", "host", "none")


@dataclass
class ProjetoCompose:
    nome: str
    pasta: str = ""
    arquivos: list[str] = field(default_factory=list)
    servicos: int = 0
    rodando: int = 0


@dataclass
class UsoDisco:
    imagens_total: int = 0
    imagens_recuperavel: int = 0
    containers_total: int = 0
    containers_recuperavel: int = 0
    volumes_total: int = 0
    volumes_recuperavel: int = 0
    cache_total: int = 0
    cache_recuperavel: int = 0

    @property
    def total(self) -> int:
        return self.imagens_total + self.containers_total + self.volumes_total + self.cache_total

    @property
    def recuperavel(self) -> int:
        return self.imagens_recuperavel + self.containers_recuperavel + self.volumes_recuperavel + self.cache_recuperavel


@dataclass
class PedidoRodar:
    imagem: str
    nome: str = ""
    portas: list[str] = field(default_factory=list)  # "8080:80"
    ambiente: list[str] = field(default_factory=list)  # "CHAVE=valor"
    volumes: list[str] = field(default_factory=list)  # "origem:destino"
    comando: str = ""
    reiniciar: bool = False
    segundo_plano: bool = True
    rotulos: dict[str, str] = field(default_factory=dict)


@dataclass
class ItemLimpeza:
    """Algo que a Limpeza pode apagar."""

    tipo: str  # container, imagem, volume, rede
    id: str
    nome: str
    tamanho: int = -1
    aviso: str = ""  # reforço, p. ex. volume com dados


class ErroDocker(Exception):
    """Erro já traduzido para linguagem clara."""


def humano(n: int) -> str:
    if n < 0:
        return "?"
    v = float(n)
    for un in ("B", "kB", "MB", "GB", "TB"):
        if v < 1000 or un == "TB":
            return f"{v:.0f} {un}" if un == "B" else f"{v:.1f} {un}".replace(".", ",")
        v /= 1000
    return str(n)
