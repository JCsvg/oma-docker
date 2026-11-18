import json

from oma_docker.services.estado import Estado, limpar_ambiente
from oma_docker.ui.abertura import banner


def test_salva_e_restaura(tmp_path):
    e = Estado(tmp_path / "r")
    e.definir("aba", "imagens")
    e2 = Estado(tmp_path / "r")
    assert e2.carregar()["aba"] == "imagens"


def test_corrompido_e_versao_antiga_sao_ignorados(tmp_path):
    e = Estado(tmp_path / "r")
    e.preparar()
    e.arquivo.write_text("{ isto nao e json")
    assert e.carregar() == {}
    e.arquivo.write_text(json.dumps({"versao": 0, "dados": {"aba": "x"}}))
    assert e.carregar() == {}
    e.arquivo.write_text(json.dumps([1, 2]))
    assert e.carregar() == {}


def test_marcador_de_abertura(tmp_path):
    e = Estado(tmp_path / "r")
    assert not e.ja_abriu()
    e.marcar_abertura()
    assert Estado(tmp_path / "r").ja_abriu()


def test_pasta_so_do_dono(tmp_path):
    e = Estado(tmp_path / "r")
    e.preparar()
    assert (tmp_path / "r").stat().st_mode & 0o777 == 0o700


def test_segredos_fora_do_rascunho():
    assert limpar_ambiente(["MODO=a", "DB_PASSWORD=x", "API_TOKEN=y", "senha=1", "AWS_SECRET_ACCESS_KEY=z"]) == ["MODO=a"]


def test_banner_grande_e_fallback():
    grande = banner(200, 50)
    assert len(grande) == 5 and max(len(l) for l in grande) <= 80
    assert banner(80, 24) == grande
    assert banner(40, 24) == ["OMA DOCKER"]
    assert banner(100, 8) == ["OMA DOCKER"]
