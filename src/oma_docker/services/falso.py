"""Cliente Docker falso, em memória. Serve aos testes e ao modo `--demo`."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterator

from oma_docker.services.modelos import (
    Container,
    ErroDocker,
    Estatistica,
    Imagem,
    PedidoRodar,
    Rede,
    UsoDisco,
    Volume,
)
from oma_docker.services.util import converter_porta

AGORA = 1_760_000_000.0
MB = 1_000_000


def _id(n: int) -> str:
    return hashlib.sha256(str(n).encode()).hexdigest()


class ClienteFalso:
    def __init__(self, vazio: bool = False, ritmo_logs: float = 0.05) -> None:
        self.chamadas: list[tuple] = []
        self.ritmo_logs = ritmo_logs
        self.trava = threading.Lock()
        self._cont: list[Container] = []
        self._img: list[Imagem] = []
        self._vol: list[Volume] = []
        self._rede: list[Rede] = []
        self._donos: dict[str, list[str]] = {}  # container -> volumes
        self._contador = 100
        if not vazio:
            self._popular()

    def _popular(self) -> None:
        for n, (tag, tam) in enumerate(
            [("postgres:16", 430), ("redis:7-alpine", 41), ("nginx:1.27", 190), ("alpine:3.22", 8), ("node:22-slim", 240), ("mysql:8", 780)]
        ):
            self._img.append(Imagem(_id(n + 1), [tag], tam * MB, AGORA - 86400 * (n + 2) * 9))
        self._img.append(Imagem(_id(9), [], 120 * MB, AGORA - 86400 * 200))
        rot = lambda p, s: {"com.docker.compose.project": p, "com.docker.compose.service": s,
                            "com.docker.compose.project.working_dir": f"/home/exemplo/{p}",
                            "com.docker.compose.project.config_files": f"/home/exemplo/{p}/compose.yml"}
        dados = [
            ("loja-api", "node:22-slim", "running", "3000->3000/tcp", "loja", "api", rot("loja", "api")),
            ("loja-db", "postgres:16", "running", "5432/tcp", "loja", "db", rot("loja", "db")),
            ("loja-cache", "redis:7-alpine", "exited", "", "loja", "cache", rot("loja", "cache")),
            ("blog-web", "nginx:1.27", "exited", "8080->80/tcp", "blog", "web", rot("blog", "web")),
            ("mysql8", "mysql:8", "exited", "3306/tcp", "", "", {}),
            ("teste-rapido", "alpine:3.22", "exited", "", "", "", {}),
        ]
        for n, (nome, img, est, portas, proj, serv, r) in enumerate(dados):
            self._cont.append(Container(_id(1000 + n), nome, img, est, "Up 2 hours" if est == "running" else "Exited (0) 3 days ago",
                                        portas, proj, serv, AGORA - 3600 * n, r))
        self._vol = [
            Volume("loja_dados", tamanho=210 * MB, em_uso=True, usado_por=["loja-db"], criado="2026-09-02"),
            Volume("mysql_dados", tamanho=380 * MB, em_uso=False, criado="2026-08-14"),
            Volume("a" * 64, tamanho=12 * MB, criado="2026-07-01"),
            Volume("b" * 64, tamanho=0, criado="2026-07-03"),
        ]
        self._donos = {"loja-db": ["loja_dados"]}
        self._rede = [
            Rede(_id(5001), "bridge", containers=1, subnet="172.17.0.0/16"),
            Rede(_id(5002), "host", driver="host"),
            Rede(_id(5003), "none", driver="null"),
            Rede(_id(5004), "loja_default", containers=2, subnet="172.18.0.0/16"),
            Rede(_id(5005), "blog_default", subnet="172.19.0.0/16"),
        ]
        self._refazer_uso()

    def _refazer_uso(self) -> None:
        em_uso = {c.imagem for c in self._cont}
        for i in self._img:
            i.em_uso = any(t in em_uso for t in i.tags)
            i.usada_por = [c.nome for c in self._cont if c.imagem in i.tags]
        for v in self._vol:
            v.usado_por = [c for c, vs in self._donos.items() if v.nome in vs]
            v.em_uso = bool(v.usado_por)

    def _achar(self, id: str) -> Container:
        for c in self._cont:
            if c.id == id or c.nome == id or c.id.startswith(id):
                return c
        raise ErroDocker("O container não existe mais.")

    def _reg(self, *a) -> None:
        self.chamadas.append(a)

    # leitura
    def versao(self) -> str:
        return "27.0 (demonstração)"

    def containers(self) -> list[Container]:
        with self.trava:
            return [Container(**{**c.__dict__}) for c in self._cont]

    def estatistica(self, id: str) -> Estatistica:
        c = self._achar(id)
        if c.estado != "running":
            raise ErroDocker("O container não está rodando.")
        k = int(c.id[-3:], 16) % 7
        return Estatistica(cpu=1.5 + k * 2.2, mem_uso=(40 + k * 30) * MB, mem_limite=8000 * MB,
                           rede_rx=k * 1200, rede_tx=k * 800, bloco_leitura=k * MB, bloco_escrita=k * 2 * MB)

    def inspecionar(self, id: str) -> dict:
        c = self._achar(id)
        return {"Name": "/" + c.nome, "Id": c.id, "Config": {"Image": c.imagem, "Cmd": ["serve"], "Env": ["MODO=exemplo"]},
                "State": {"Status": c.estado}, "Mounts": [{"Name": v, "Destination": "/dados", "Type": "volume"} for v in self._donos.get(c.nome, [])],
                "NetworkSettings": {"Ports": {}, "Networks": {"bridge": {}}}, "HostConfig": {"RestartPolicy": {"Name": ""}}}

    def imagens(self) -> list[Imagem]:
        with self.trava:
            self._refazer_uso()
            return [Imagem(**{**i.__dict__}) for i in self._img]

    def volumes(self) -> list[Volume]:
        with self.trava:
            self._refazer_uso()
            return [Volume(**{**v.__dict__}) for v in self._vol]

    def redes(self) -> list[Rede]:
        with self.trava:
            return [Rede(**{**r.__dict__}) for r in self._rede]

    def uso_disco(self) -> UsoDisco:
        u = UsoDisco()
        for i in self.imagens():
            u.imagens_total += i.tamanho
            if not i.em_uso:
                u.imagens_recuperavel += i.tamanho
        for v in self.volumes():
            u.volumes_total += max(v.tamanho, 0)
            if not v.em_uso:
                u.volumes_recuperavel += max(v.tamanho, 0)
        for c in self.containers():
            u.containers_total += 2 * MB
            if not c.rodando:
                u.containers_recuperavel += 2 * MB
        return u

    # ações
    def _estado(self, id: str, novo: str, rotulo: str) -> None:
        self._reg(rotulo, id)
        with self.trava:
            c = self._achar(id)
            c.estado = novo
            c.status = {"running": "Up 1 second", "exited": "Exited (0) agora", "paused": "Up (Paused)"}[novo]

    def iniciar(self, id: str) -> None:
        with self.trava:
            c = self._achar(id)
            for p in c.portas.split(", "):
                if "->" in p:
                    h = p.split("->")[0]
                    for o in self._cont:
                        if o is not c and o.estado == "running" and f"{h}->" in o.portas:
                            raise RuntimeError(f"Bind for 0.0.0.0:{h} failed: port is already allocated")
        self._estado(id, "running", "iniciar")

    def parar(self, id: str) -> None:
        self._estado(id, "exited", "parar")

    def reiniciar(self, id: str) -> None:
        self._estado(id, "running", "reiniciar")

    def pausar(self, id: str) -> None:
        self._estado(id, "paused", "pausar")

    def retomar(self, id: str) -> None:
        self._estado(id, "running", "retomar")

    def remover_container(self, id: str, forcar: bool = False) -> None:
        self._reg("remover_container", id, forcar)
        with self.trava:
            c = self._achar(id)
            if c.rodando and not forcar:
                raise RuntimeError("You cannot remove a running container. Stop the container before attempting removal or force remove")
            self._cont.remove(c)
            self._donos.pop(c.nome, None)

    def logs(self, id: str, seguir: bool = True, fim: int = 200) -> Iterator[str]:
        c = self._achar(id)
        for n in range(3):
            yield f"[{c.nome}] linha {n} de exemplo"
        n = 3
        while seguir and self._achar(id).estado == "running":
            time.sleep(self.ritmo_logs)
            yield f"[{c.nome}] linha {n} de exemplo"
            n += 1

    def rodar(self, pedido: PedidoRodar) -> str:
        self._reg("rodar", pedido)
        with self.trava:
            if not any(pedido.imagem in i.tags or pedido.imagem + ":latest" in i.tags for i in self._img):
                raise RuntimeError(f"pull access denied for {pedido.imagem}, repository does not exist")
            if pedido.nome and any(c.nome == pedido.nome for c in self._cont):
                raise RuntimeError(f'Conflict. The container name "/{pedido.nome}" is already in use')
            pub = []
            for p in pedido.portas:
                k, v = converter_porta(p)
                if v is not None:
                    h = v[1] if isinstance(v, tuple) else v
                    if any(f"{h}->" in c.portas and c.estado == "running" for c in self._cont):
                        raise RuntimeError(f"Bind for 0.0.0.0:{h} failed: port is already allocated")
                    pub.append(f"{h}->{k}")
            self._contador += 1
            nome = pedido.nome or f"container_{self._contador}"
            self._cont.append(Container(_id(self._contador), nome, pedido.imagem, "running", "Up 1 second",
                                        ", ".join(pub), "", "", AGORA, dict(pedido.rotulos)))
            self._donos[nome] = [v.split(":")[0] for v in pedido.volumes]
            return nome

    def baixar_imagem(self, ref: str, progresso: Callable[[str], None]) -> None:
        self._reg("baixar", ref)
        if "inexistente" in ref:
            raise RuntimeError("pull access denied, repository does not exist")
        for p in (10, 60, 100):
            progresso(f"Baixando {p}%")
        with self.trava:
            tag = ref if ":" in ref else ref + ":latest"
            self._contador += 1
            self._img.append(Imagem(_id(self._contador), [tag], 20 * MB, AGORA))

    def remover_imagem(self, id: str, forcar: bool = False) -> None:
        self._reg("remover_imagem", id)
        with self.trava:
            for i in self._img:
                if i.id == id or id in i.tags:
                    if any(c.imagem in i.tags for c in self._cont):
                        raise RuntimeError("conflict: unable to delete, image is being used by stopped container")
                    self._img.remove(i)
                    return
        raise ErroDocker("A imagem não existe mais.")

    def criar_volume(self, nome: str) -> None:
        self._reg("criar_volume", nome)
        with self.trava:
            if any(v.nome == nome for v in self._vol):
                raise ErroDocker(f"Já existe um volume chamado {nome}.")
            self._vol.append(Volume(nome, tamanho=0, criado="2026-11-17"))

    def remover_volume(self, nome: str) -> None:
        self._reg("remover_volume", nome)
        with self.trava:
            v = next((v for v in self._vol if v.nome == nome), None)
            if v is None:
                raise ErroDocker("O volume não existe mais.")
            if any(nome in vs for vs in self._donos.values()):
                raise RuntimeError("remove: volume is in use")
            self._vol.remove(v)

    def criar_rede(self, nome: str, driver: str = "bridge") -> None:
        self._reg("criar_rede", nome)
        with self.trava:
            self._contador += 1
            self._rede.append(Rede(_id(5000 + self._contador), nome, driver))

    def remover_rede(self, id: str) -> None:
        self._reg("remover_rede", id)
        with self.trava:
            r = next((r for r in self._rede if r.id == id or r.nome == id), None)
            if r is None:
                raise ErroDocker("A rede não existe mais.")
            if r.padrao:
                raise RuntimeError("bridge is a pre-defined network and cannot be removed")
            if r.containers:
                raise RuntimeError("network has active endpoints")
            self._rede.remove(r)

    def compose(self, projeto: str, acao: str, pasta: str = "", arquivos: list[str] | None = None) -> None:
        self._reg("compose", projeto, acao)
        novo = {"subir": "running", "parar": "exited", "reiniciar": "running"}[acao]
        for c in list(self._cont):
            if c.projeto == projeto:
                self._estado(c.id, novo, "compose")

    def fechar(self) -> None:
        pass
