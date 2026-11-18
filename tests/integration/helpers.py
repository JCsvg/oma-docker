from textual.widgets import DataTable

from tests.conftest import esperar


async def abrir(app, pilot, tecla, cls):
    await pilot.press(tecla)
    aba = app.query_one(cls)
    assert await esperar(pilot, lambda: aba.carregado)
    await esperar(pilot, lambda: aba.query_one("#tabela", DataTable).row_count > 0 or aba.query_one("#vazio").display)
    await pilot.pause(0.1)
    return aba


async def ir_para(pilot, aba, chave):
    t = aba.query_one("#tabela", DataTable)
    idx = [k.value for k in t.rows].index(chave)
    t.move_cursor(row=idx, animate=False)
    t.focus()
    await pilot.pause(0.05)


def avisos(app):
    return [n.message for n in app._notifications]
