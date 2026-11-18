"""Interface fina do cliente Docker e a implementação com o SDK (docker-py)."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Iterator
from typing import Protocol

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
from oma_docker.services.util import (
    converter_ambiente,
    converter_porta,
    converter_volumes,
)


class ClienteDocker(Protocol):
    def containers(self) -> list[Container]: ...
    def estatistica(self, id: str) -> Estatistica: ...
    def inspecionar(self, id: str) -> dict: ...
    def iniciar(self, id: str) -> None: ...
    def parar(self, id: str) -> None: ...
    def reiniciar(self, id: str) -> None: ...
    def pausar(self, id: str) -> None: ...
    def retomar(self, id: str) -> None: ...
    def remover_container(self, id: str, forcar: bool = False) -> None: ...
    def logs(self, id: str, seguir: bool = True, fim: int = 200) -> Iterator[str]: ...
    def rodar(self, pedido: PedidoRodar) -> str: ...
    def imagens(self) -> list[Imagem]: ...
    def baixar_imagem(self, ref: str, progresso: Callable[[str], None]) -> None: ...
    def remover_imagem(self, id: str, forcar: bool = False) -> None: ...
    def volumes(self) -> list[Volume]: ...
    def criar_volume(self, nome: str) -> None: ...
    def remover_volume(self, nome: str) -> None: ...
    def redes(self) -> list[Rede]: ...
    def criar_rede(self, nome: str, driver: str = "bridge") -> None: ...
    def remover_rede(self, id: str) -> None: ...
    def uso_disco(self) -> UsoDisco: ...
    def compose(self, projeto: str, acao: str, pasta: str = "", arquivos: list[str] | None = None) -> None: ...
    def versao(self) -> str: ...
    def fechar(self) -> None: ...


def _portas(lista: list[dict]) -> str:
    vistos: list[str] = []
    for p in lista or []:
        priv, tipo = p.get("PrivatePort"), p.get("Type", "tcp")
        if p.get("PublicPort"):
            t = f"{p['PublicPort']}->{priv}/{tipo}"
        else:
            t = f"{priv}/{tipo}"
        if t not in vistos:
            vistos.append(t)
    return ", ".join(vistos)


class ClienteSDK:
    """Fala com /var/run/docker.sock pelo docker-py. O compose é o `docker compose` externo."""

    def __init__(self, api=None) -> None:
        if api is None:
            import docker

            api = docker.APIClient(base_url="unix:///var/run/docker.sock", timeout=30)
        self.api = api

    # leitura
    def versao(self) -> str:
        return self.api.version().get("Version", "?")

    def _brutos(self) -> list[dict]:
        return self.api.containers(all=True)

    def containers(self) -> list[Container]:
        saida = []
        for c in self._brutos():
            rot = c.get("Labels") or {}
            saida.append(
                Container(
                    id=c["Id"],
                    nome=(c.get("Names") or ["/?"])[0].lstrip("/"),
                    imagem=c.get("Image", ""),
                    estado=c.get("State", ""),
                    status=c.get("Status", ""),
                    portas=_portas(c.get("Ports")),
                    projeto=rot.get("com.docker.compose.project", ""),
                    servico=rot.get("com.docker.compose.service", ""),
                    criado=float(c.get("Created", 0)),
                    rotulos=rot,
                )
            )
        return saida

    def inspecionar(self, id: str) -> dict:
        return self.api.inspect_container(id)

    def estatistica(self, id: str) -> Estatistica:
        s = self.api.stats(id, stream=False)
        cpu = s.get("cpu_stats", {})
        pre = s.get("precpu_stats", {})
        d_cpu = cpu.get("cpu_usage", {}).get("total_usage", 0) - pre.get("cpu_usage", {}).get("total_usage", 0)
        d_sys = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        n = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or []) or 1
        pct = (d_cpu / d_sys) * n * 100 if d_sys > 0 and d_cpu >= 0 else 0.0
        mem = s.get("memory_stats", {})
        uso = mem.get("usage", 0) - mem.get("stats", {}).get("inactive_file", 0)
        rede = s.get("networks") or {}
        io = (s.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []
        return Estatistica(
            cpu=pct,
            mem_uso=max(uso, 0),
            mem_limite=mem.get("limit", 0),
            rede_rx=sum(v.get("rx_bytes", 0) for v in rede.values()),
            rede_tx=sum(v.get("tx_bytes", 0) for v in rede.values()),
            bloco_leitura=sum(e.get("value", 0) for e in io if str(e.get("op")).lower() == "read"),
            bloco_escrita=sum(e.get("value", 0) for e in io if str(e.get("op")).lower() == "write"),
        )

    def imagens(self) -> list[Imagem]:
        uso: dict[str, list[str]] = {}
        for c in self._brutos():
            uso.setdefault(c.get("ImageID", ""), []).append((c.get("Names") or ["/?"])[0].lstrip("/"))
        saida = []
        for i in self.api.images():
            tags = [t for t in (i.get("RepoTags") or []) if t != "<none>:<none>"]
            saida.append(
                Imagem(id=i["Id"], tags=tags, tamanho=i.get("Size", 0), criada=float(i.get("Created", 0)),
                       em_uso=i["Id"] in uso, usada_por=uso.get(i["Id"], []))
            )
        return saida

    def volumes(self) -> list[Volume]:
        uso: dict[str, list[str]] = {}
        for c in self._brutos():
            for m in c.get("Mounts") or []:
                if m.get("Type") == "volume":
                    uso.setdefault(m.get("Name", ""), []).append((c.get("Names") or ["/?"])[0].lstrip("/"))
        tamanhos: dict[str, int] = {}
        try:
            for v in self.api.df().get("Volumes") or []:
                tamanhos[v["Name"]] = (v.get("UsageData") or {}).get("Size", -1)
        except Exception:
            pass
        saida = []
        for v in (self.api.volumes().get("Volumes") or []):
            n = v["Name"]
            saida.append(
                Volume(nome=n, driver=v.get("Driver", "local"), tamanho=tamanhos.get(n, -1),
                       em_uso=n in uso, usado_por=uso.get(n, []), criado=(v.get("CreatedAt") or "")[:10],
                       rotulos=v.get("Labels") or {})
            )
        return saida

    def redes(self) -> list[Rede]:
        contagem: dict[str, int] = {}
        for c in self._brutos():
            for r in ((c.get("NetworkSettings") or {}).get("Networks") or {}).values():
                contagem[r.get("NetworkID", "")] = contagem.get(r.get("NetworkID", ""), 0) + 1
        saida = []
        for r in self.api.networks():
            cfg = ((r.get("IPAM") or {}).get("Config") or [{}])
            saida.append(
                Rede(id=r["Id"], nome=r["Name"], driver=r.get("Driver", ""), escopo=r.get("Scope", ""),
                     subnet=(cfg[0] or {}).get("Subnet", ""), containers=contagem.get(r["Id"], 0))
            )
        return saida

    def uso_disco(self) -> UsoDisco:
        df = self.api.df()
        conts = self._brutos()
        usadas = {c.get("ImageID") for c in conts}
        u = UsoDisco()
        for i in df.get("Images") or []:
            u.imagens_total += max(i.get("Size", 0), 0)
            if i["Id"] not in usadas:
                u.imagens_recuperavel += max(i.get("Size", 0), 0)
        for c in df.get("Containers") or []:
            t = max(c.get("SizeRw") or 0, 0)
            u.containers_total += t
            if c.get("State") != "running":
                u.containers_recuperavel += t
        emuso = {m.get("Name") for c in conts for m in c.get("Mounts") or [] if m.get("Type") == "volume"}
        for v in df.get("Volumes") or []:
            t = max((v.get("UsageData") or {}).get("Size", 0), 0)
            u.volumes_total += t
            if v["Name"] not in emuso:
                u.volumes_recuperavel += t
        for b in df.get("BuildCache") or []:
            t = max(b.get("Size", 0), 0)
            u.cache_total += t
            if not b.get("InUse"):
                u.cache_recuperavel += t
        return u

    # ações
    def iniciar(self, id: str) -> None:
        self.api.start(id)

    def parar(self, id: str) -> None:
        self.api.stop(id, timeout=10)

    def reiniciar(self, id: str) -> None:
        self.api.restart(id, timeout=10)

    def pausar(self, id: str) -> None:
        self.api.pause(id)

    def retomar(self, id: str) -> None:
        self.api.unpause(id)

    def remover_container(self, id: str, forcar: bool = False) -> None:
        self.api.remove_container(id, force=forcar)

    def logs(self, id: str, seguir: bool = True, fim: int = 200) -> Iterator[str]:
        fluxo = self.api.logs(id, stream=True, follow=seguir, tail=fim)
        try:
            resto = b""
            for pedaco in fluxo:
                resto += pedaco
                *linhas, resto = resto.split(b"\n")
                for l in linhas:
                    yield l.decode("utf-8", "replace")
            if resto:
                yield resto.decode("utf-8", "replace")
        finally:
            try:
                fluxo.close()
            except Exception:
                pass

    def rodar(self, pedido: PedidoRodar) -> str:
        portas: dict = {}
        for p in pedido.portas:
            k, v = converter_porta(p)
            portas[k] = v
        host = self.api.create_host_config(
            port_bindings=portas,
            binds=converter_volumes(pedido.volumes),
            restart_policy={"Name": "always"} if pedido.reiniciar else None,
        )
        cont = self.api.create_container(
            pedido.imagem,
            command=pedido.comando or None,
            name=pedido.nome or None,
            ports=[k for k in portas] or None,
            environment=converter_ambiente(pedido.ambiente),
            host_config=host,
            labels=pedido.rotulos or None,
        )
        self.api.start(cont["Id"])
        return pedido.nome or cont["Id"][:12]

    def baixar_imagem(self, ref: str, progresso: Callable[[str], None]) -> None:
        repo, tag = (ref.rsplit(":", 1) if ":" in ref.rsplit("/", 1)[-1] else (ref, "latest"))
        for ev in self.api.pull(repo, tag=tag, stream=True, decode=True):
            if "error" in ev:
                raise ErroDocker(ev["error"])
            pd = ev.get("progressDetail") or {}
            txt = ev.get("status", "")
            if pd.get("total"):
                txt += f" {pd.get('current', 0) * 100 // pd['total']}%"
            progresso(txt)

    def remover_imagem(self, id: str, forcar: bool = False) -> None:
        self.api.remove_image(id, force=forcar)

    def criar_volume(self, nome: str) -> None:
        self.api.create_volume(name=nome)

    def remover_volume(self, nome: str) -> None:
        self.api.remove_volume(nome)

    def criar_rede(self, nome: str, driver: str = "bridge") -> None:
        self.api.create_network(nome, driver=driver)

    def remover_rede(self, id: str) -> None:
        self.api.remove_network(id)

    def compose(self, projeto: str, acao: str, pasta: str = "", arquivos: list[str] | None = None) -> None:
        cmd = ["docker", "compose", "-p", projeto]
        if pasta:
            cmd += ["--project-directory", pasta]
        for a in arquivos or []:
            cmd += ["-f", a]
        cmd += {"subir": ["up", "-d"], "parar": ["stop"], "reiniciar": ["restart"]}[acao]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except FileNotFoundError as e:
            raise ErroDocker("O comando `docker compose` não foi encontrado. Instale docker-compose.") from e
        except subprocess.TimeoutExpired as e:
            raise ErroDocker("O compose demorou demais (mais de 5 minutos).") from e
        if r.returncode != 0:
            ult = [l for l in r.stderr.strip().splitlines() if l.strip()]
            raise ErroDocker("O compose falhou: " + (ult[-1] if ult else f"código {r.returncode}"))

    def fechar(self) -> None:
        try:
            self.api.close()
        except Exception:
            pass
