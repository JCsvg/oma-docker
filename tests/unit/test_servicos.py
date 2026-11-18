import pytest

from oma_docker.services.erros import traduzir
from oma_docker.services.falso import ClienteFalso
from oma_docker.services.modelos import Container, ErroDocker, PedidoRodar, Volume, humano
from oma_docker.services.util import (
    converter_ambiente,
    converter_porta,
    converter_volumes,
    itens_de_limpeza,
    projetos_de,
    separar_portas,
)


def test_humano():
    assert humano(0) == "0 B"
    assert humano(1_500_000) == "1,5 MB"
    assert humano(-1) == "?"
    assert humano(2_000_000_000) == "2,0 GB"


def test_portas():
    assert converter_porta("8080:80") == ("80/tcp", 8080)
    assert converter_porta("80") == ("80/tcp", None)
    assert converter_porta("53:53/udp") == ("53/udp", 53)
    assert converter_porta("127.0.0.1:8080:80") == ("80/tcp", ("127.0.0.1", 8080))
    with pytest.raises(ErroDocker):
        converter_porta("abc:80")
    assert separar_portas("8080:80, 81:81") == ["8080:80", "81:81"]


def test_validacao_ambiente_e_volumes():
    assert converter_ambiente(["A=1"]) == ["A=1"]
    with pytest.raises(ErroDocker):
        converter_ambiente(["sem_igual"])
    with pytest.raises(ErroDocker):
        converter_volumes(["so_origem"])


@pytest.mark.parametrize("bruto,esperado", [
    ("Bind for 0.0.0.0:8080 failed: port is already allocated", "A porta 8080 já está em uso"),
    ('Conflict. The container name "/web" is already in use', "Já existe um container chamado web"),
    ("remove: volume is in use", "O volume está em uso"),
    ("network has active endpoints", "A rede tem containers conectados"),
    ("pull access denied for x, repository does not exist", "Imagem não encontrada"),
    ("permission denied while trying to connect to the docker.sock", "Sem permissão"),
])
def test_traducao_de_erros(bruto, esperado):
    assert esperado in traduzir(RuntimeError(bruto))


def test_erro_desconhecido_nao_vaza_stack():
    msg = traduzir(RuntimeError("algo estranho\nlinha 2 traceback"))
    assert msg.startswith("O Docker recusou") and "\n" not in msg


def test_projetos_e_limpeza():
    f = ClienteFalso()
    proj = projetos_de(f.containers())
    assert [p.nome for p in proj] == ["blog", "loja"]
    loja = proj[1]
    assert (loja.servicos, loja.rodando) == (3, 2)
    itens = itens_de_limpeza(f.containers(), f.imagens(), f.volumes(), f.redes())
    tipos = {i.tipo for i in itens}
    assert tipos == {"container", "imagem", "volume", "rede"}
    assert not any(i.tipo == "rede" and i.nome in ("bridge", "host", "none") for i in itens)
    assert not any(i.tipo == "volume" and i.nome.startswith("loja_dados") for i in itens)


def test_volume_anonimo():
    assert Volume("a" * 64).anonimo and not Volume("dados").anonimo
    assert Container("1", "x", "i", "running").rodando


def test_falso_ciclo_de_vida():
    f = ClienteFalso()
    nome = f.rodar(PedidoRodar("alpine:3.22", nome="novo", portas=["9090:80"]))
    assert nome == "novo"
    with pytest.raises(RuntimeError, match="already allocated"):
        f.rodar(PedidoRodar("alpine:3.22", nome="outro", portas=["9090:80"]))
    with pytest.raises(RuntimeError, match="running container"):
        f.remover_container("novo")
    f.parar("novo")
    f.remover_container("novo")
    assert all(c.nome != "novo" for c in f.containers())


def test_falso_compose_e_volume_em_uso():
    f = ClienteFalso()
    f.compose("blog", "subir")
    assert next(c for c in f.containers() if c.nome == "blog-web").estado == "running"
    with pytest.raises(RuntimeError, match="in use"):
        f.remover_volume("loja_dados")


def test_logs_do_falso():
    f = ClienteFalso(ritmo_logs=0)
    it = f.logs("mysql8", seguir=False)
    assert len(list(it)) == 3
