"""Traduz erros do Docker para mensagens claras em português."""

from __future__ import annotations

import re

from oma_docker.services.modelos import ErroDocker


def traduzir(exc: BaseException) -> str:
    if isinstance(exc, ErroDocker):
        return str(exc)
    bruto = str(getattr(exc, "explanation", None) or exc)
    baixo = bruto.lower()
    if m := re.search(r"bind for [\d.:]*?:(\d+) failed: port is already allocated", baixo) or re.search(
        r"port (\d+) is already allocated|address already in use.*?(\d+)", baixo
    ):
        porta = next(g for g in m.groups() if g)
        return f"A porta {porta} já está em uso. Escolha outra porta do host."
    if "permission denied" in baixo and "docker.sock" in baixo:
        return "Sem permissão para falar com o Docker. Seu usuário precisa estar no grupo docker."
    if "connection refused" in baixo or "no such file or directory" in baixo and "docker.sock" in baixo or "error while fetching server api version" in baixo:
        return "Não consegui falar com o Docker. O serviço está rodando? (systemctl start docker)"
    if "conflict" in baixo and "container name" in baixo:
        m = re.search(r'name "/?([^"]+)"', bruto)
        return f"Já existe um container chamado {m.group(1) if m else 'com esse nome'}. Escolha outro nome."
    if "image is being used by" in baixo or "image is referenced in multiple" in baixo or "conflict: unable to delete" in baixo:
        return "A imagem está em uso por um container. Remova o container antes."
    if "volume is in use" in baixo:
        return "O volume está em uso por um container. Remova o container antes."
    if "active endpoints" in baixo or "has active endpoints" in baixo:
        return "A rede tem containers conectados. Desconecte ou remova os containers antes."
    if "pre-defined network" in baixo:
        return "Redes padrão do Docker (bridge, host, none) não podem ser apagadas."
    if "cannot remove a running container" in baixo or "stop the container before attempting removal" in baixo:
        return "O container está rodando. Pare antes de remover."
    if "pull access denied" in baixo or "repository does not exist" in baixo or "not found" in baixo and "image" in baixo:
        return "Imagem não encontrada. Confira o nome e a tag."
    if "no such container" in baixo:
        return "O container não existe mais."
    if "is not running" in baixo:
        return "O container não está rodando."
    if "executable file not found" in baixo or "no such file or directory" in baixo and "exec" in baixo:
        return "O comando não existe dentro da imagem."
    if "invalid reference format" in baixo:
        return "Nome de imagem inválido."
    linha = bruto.strip().splitlines()[0] if bruto.strip() else type(exc).__name__
    return f"O Docker recusou a operação: {linha[:200]}"
