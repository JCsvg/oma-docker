"""Funções puras: portas, projetos compose, itens de limpeza."""

from __future__ import annotations

from oma_docker.services.modelos import (
    Container,
    ErroDocker,
    Imagem,
    ItemLimpeza,
    ProjetoCompose,
    Rede,
    Volume,
)


def separar_portas(texto: str) -> list[str]:
    return [p.strip() for p in texto.replace(",", " ").split() if p.strip()]


def converter_porta(entrada: str) -> tuple[str, object]:
    """'8080:80', '127.0.0.1:8080:80/udp' ou '80' viram a chave/valor do SDK."""
    corpo, _, proto = entrada.partition("/")
    proto = proto or "tcp"
    partes = corpo.split(":")
    try:
        if len(partes) == 1:
            return f"{int(partes[0])}/{proto}", None
        if len(partes) == 2:
            return f"{int(partes[1])}/{proto}", int(partes[0])
        if len(partes) == 3:
            return f"{int(partes[2])}/{proto}", (partes[0], int(partes[1]))
    except ValueError:
        pass
    raise ErroDocker(f"Porta inválida: {entrada}. Use host:container, por exemplo 8080:80.")


def converter_ambiente(linhas: list[str]) -> list[str]:
    saida = []
    for l in linhas:
        if "=" not in l or l.startswith("="):
            raise ErroDocker(f"Variável inválida: {l}. Use CHAVE=valor.")
        saida.append(l)
    return saida


def converter_volumes(linhas: list[str]) -> list[str]:
    for l in linhas:
        if ":" not in l or l.startswith(":") or l.endswith(":"):
            raise ErroDocker(f"Volume inválido: {l}. Use origem:destino, por exemplo meu_volume:/dados.")
    return linhas


def projetos_de(containers: list[Container]) -> list[ProjetoCompose]:
    por: dict[str, ProjetoCompose] = {}
    servicos: dict[str, set[str]] = {}
    for c in containers:
        if not c.projeto:
            continue
        p = por.setdefault(c.projeto, ProjetoCompose(nome=c.projeto))
        p.pasta = p.pasta or c.rotulos.get("com.docker.compose.project.working_dir", "")
        cfg = c.rotulos.get("com.docker.compose.project.config_files", "")
        if cfg and not p.arquivos:
            p.arquivos = [a for a in cfg.split(",") if a]
        servicos.setdefault(c.projeto, set()).add(c.servico or c.nome)
        if c.estado == "running":
            p.rodando += 1
    for n, p in por.items():
        p.servicos = len(servicos[n])
    return sorted(por.values(), key=lambda p: p.nome)


def itens_de_limpeza(
    containers: list[Container], imagens: list[Imagem], volumes: list[Volume], redes: list[Rede]
) -> list[ItemLimpeza]:
    itens: list[ItemLimpeza] = []
    for c in containers:
        if not c.rodando:
            itens.append(ItemLimpeza("container", c.id, c.nome, -1, ""))
    for i in imagens:
        if not i.em_uso:
            itens.append(ItemLimpeza("imagem", i.id, i.nome if i.tags else i.curto, i.tamanho))
    for v in volumes:
        if not v.em_uso:
            aviso = "pode ter dados que não voltam" if v.tamanho != 0 else ""
            itens.append(ItemLimpeza("volume", v.nome, v.nome_curto + (" (sem nome)" if v.anonimo else ""), v.tamanho, aviso))
    for r in redes:
        if not r.padrao and r.containers == 0:
            itens.append(ItemLimpeza("rede", r.id, r.nome, -1))
    return itens
