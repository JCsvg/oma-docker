from __future__ import annotations

import asyncio

import pytest

from oma_docker.app import OmaDockerApp
from oma_docker.services.estado import Estado
from oma_docker.services.falso import ClienteFalso
from oma_docker.services.terminal import Tmux


@pytest.fixture
def estado(tmp_path):
    return Estado(tmp_path / "run")


@pytest.fixture
def falso():
    return ClienteFalso()


@pytest.fixture
def anexos():
    return []


@pytest.fixture
def app(falso, estado, anexos):
    return OmaDockerApp(cliente=falso, estado=estado, tmux=Tmux(estado.pasta / "tmux.sock"), abertura=False, anexador=anexos.append)


async def esperar(pilot, cond, tempo=3.0):
    """Espera uma condição (as chamadas ao Docker rodam em threads)."""
    fim = asyncio.get_event_loop().time() + tempo
    while asyncio.get_event_loop().time() < fim:
        await pilot.pause(0.05)
        if cond():
            return True
    return cond()
