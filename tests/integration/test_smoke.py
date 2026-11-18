from oma_docker.ui.abas import AbaContainers
from tests.conftest import esperar


async def test_abre(app):
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("2")
        aba = app.query_one(AbaContainers)
        assert await esperar(pilot, lambda: aba.carregado)
        assert aba.query_one("#tabela").row_count > 5
