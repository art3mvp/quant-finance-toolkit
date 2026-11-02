"""Simulación de Monte Carlo (movimiento browniano geométrico)."""

from __future__ import annotations

import numpy as np


def simulate_gbm(
    initial_value: float,
    mu: float,
    sigma: float,
    n_steps: int,
    n_simulations: int,
    seed: int | None = None,
) -> np.ndarray:
    """Simula trayectorias de un valor con movimiento browniano geométrico.

    Args:
        initial_value: Valor de partida (precio o valor de la cartera).
        mu: Retorno esperado por periodo (misma unidad que ``sigma``).
        sigma: Volatilidad por periodo.
        n_steps: Horizonte temporal en periodos.
        n_simulations: Número de trayectorias.
        seed: Semilla para reproducibilidad.

    Returns:
        Array de forma ``(n_steps + 1, n_simulations)``; la fila 0 es ``initial_value``.
    """
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_steps, n_simulations))
    log_steps = (mu - 0.5 * sigma**2) + sigma * z
    paths = initial_value * np.exp(np.cumsum(log_steps, axis=0))
    return np.vstack([np.full(n_simulations, initial_value), paths])