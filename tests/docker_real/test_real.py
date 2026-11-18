"""Contra o Docker real: só LÊ, e o que cria leva o rótulo oma-docker-test=1 (imagem alpine:3.22 que já existe).

Rodar com:  uv run pytest -m docker
No fim, remove só o que tem o rótulo. Nada que não tenha o rótulo é tocado.
"""

import time

import pytest

from oma_docker.services.cliente import ClienteSDK
from oma_docker.services.modelos import PedidoRodar

pytestmark = pytest.mark.docker
ROTULO = {"oma-docker-test": "1"}
FILTRO = {"label": "oma-docker-test=1"}
IMAGEM = "alpine:3.22"


@pytest.fixture(scope="module")
def cli():
    try:
        c = ClienteSDK()
        c.versao()
    except Exception as e:
        pytest.skip(f"Docker indisponível: {e}")
    yield c
    limpar(c)
    c.fechar()


def limpar(c: ClienteSDK) -> None:
    for x in c.api.containers(all=True, filters=FILTRO):
        c.api.remove_container(x["Id"], force=True)
    for v in c.api.volumes(filters=FILTRO).get("Volumes") or []:
        c.api.remove_volume(v["Name"])
    for r in c.api.networks(filters=FILTRO):
        c.api.remove_network(r["Id"])


def test_listagens_so_leitura(cli):
    assert cli.versao()
    conts, imgs, vols, redes = cli.containers(), cli.imagens(), cli.volumes(), cli.redes()
    assert all(c.id and c.nome for c in conts)
    assert all(i.tamanho >= 0 for i in imgs)
    assert {r.nome for r in redes} >= {"bridge", "host", "none"}
    uso = cli.uso_disco()
    assert uso.total >= uso.recuperavel >= 0
    assert len({v.nome for v in vols}) == len(vols)


def test_ciclo_de_vida_com_rotulo(cli):
    if not any(IMAGEM in i.tags for i in cli.imagens()):
        pytest.skip(f"{IMAGEM} não existe localmente (não baixo imagens em teste)")
    nome = f"oma-docker-test-{int(time.time())}"
    cli.rodar(PedidoRodar(IMAGEM, nome=nome, comando="sleep 60", rotulos=ROTULO))
    c = next(c for c in cli.containers() if c.nome == nome)
    assert c.estado == "running" and c.rotulos.get("oma-docker-test") == "1"
    assert cli.estatistica(c.id).mem_limite > 0
    assert cli.inspecionar(c.id)["Config"]["Image"] == IMAGEM
    cli.pausar(c.id)
    assert next(x for x in cli.containers() if x.id == c.id).estado == "paused"
    cli.retomar(c.id)
    cli.parar(c.id)
    cli.iniciar(c.id)
    cli.reiniciar(c.id)
    linhas = list(cli.logs(c.id, seguir=False, fim=5))
    assert isinstance(linhas, list)
    with pytest.raises(Exception, match="(?i)running"):
        cli.remover_container(c.id)
    cli.parar(c.id)
    cli.remover_container(c.id)
    assert all(x.nome != nome for x in cli.containers())


def test_volume_e_rede_com_rotulo(cli):
    n = f"oma-docker-test-vol-{int(time.time())}"
    cli.api.create_volume(name=n, labels=ROTULO)
    v = next(v for v in cli.volumes() if v.nome == n)
    assert not v.anonimo and not v.em_uso
    cli.remover_volume(n)
    r = f"oma-docker-test-net-{int(time.time())}"
    cli.api.create_network(r, labels=ROTULO)
    assert any(x.nome == r for x in cli.redes())
    cli.remover_rede(next(x.id for x in cli.redes() if x.nome == r))


def test_erro_real_de_porta_ocupada_vira_texto_claro(cli):
    """Pede a mesma porta duas vezes (só containers com rótulo, na 127.0.0.1)."""
    from oma_docker.services.erros import traduzir

    if not any(IMAGEM in i.tags for i in cli.imagens()):
        pytest.skip("sem alpine")
    base = int(time.time()) % 1000
    porta = 28000 + base
    a = f"oma-docker-test-a-{base}"
    cli.rodar(PedidoRodar(IMAGEM, nome=a, comando="sleep 60", portas=[f"127.0.0.1:{porta}:80"], rotulos=ROTULO))
    with pytest.raises(Exception) as e:
        cli.rodar(PedidoRodar(IMAGEM, nome=a + "b", comando="sleep 60", portas=[f"127.0.0.1:{porta}:80"], rotulos=ROTULO))
    assert f"porta {porta}" in traduzir(e.value)
