"""Guarda de memória: o RSS depois de uso intenso não pode passar de um teto."""
from __future__ import annotations

import gc
import os

from oma_docker.ui.abas import ABAS
from oma_docker.ui.dialogos import TelaLogs

TETO_MB = 160  # medido 60-80 MB isolado, 108 MB na suite inteira (RSS herdado dos outros testes)
TETO_CRESCIMENTO_MB = 25  # pós-uso menos pós-aquecimento


def rss_mb() -> float:
    with open(f"/proc/{os.getpid()}/status") as f:
        for linha in f:
            if linha.startswith("VmRSS:"):
                return int(linha.split()[1]) / 1024
    return 0.0


async def _uso(app, pilot, voltas: int) -> None:
    for _ in range(voltas):
        for nome, *_ in ABAS:
            app.action_aba(nome)
            await pilot.pause(0.01)
        app.cliente.ritmo_logs = 0.001
        nome_c = app.cliente.containers()[0]
        app.push_screen(TelaLogs(app.cliente, nome_c.id, nome_c.nome))
        await pilot.pause(0.05)
        app.screen.action_fechar()
        await pilot.pause(0.02)
    gc.collect()


async def test_rss_nao_cresce_com_o_uso(app):
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await _uso(app, pilot, 3)
        base = rss_mb()
        await _uso(app, pilot, 30)
        fim = rss_mb()
        print(f"RSS aquecido {base:.1f} MB, pos-uso {fim:.1f} MB")
        assert fim < TETO_MB
        assert fim - base < TETO_CRESCIMENTO_MB
